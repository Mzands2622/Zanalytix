import logging
import re
import copy
import aiohttp
import asyncio
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# --- From your original code references ---
from function_app import (
    fetch_with_zyte,       # or your own fetch approach
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# ---------------------------------------------------------------------
# 1) Fetch the pipeline URL or HTML
# ---------------------------------------------------------------------
async def fetch_teva_html():
    """
    Returns the Teva pipeline URL for the caller to fetch HTML from.
    If you prefer to fetch the HTML here, you can do so (e.g. calling fetch_with_zyte).
    """
    try:
        # If you want to return only the URL, do this:
        url = "https://www.tevapharm.com/product-focus/research/pipeline/"
        return url

        # Or, if you prefer to return actual HTML, you could do:
        # url = "https://www.tevapharm.com/product-focus/research/pipeline/"
        # html_content = await fetch_with_zyte(url)
        # return html_content

    except Exception as e:
        logging.error(f"Error fetching Teva pipeline URL: {e}")
        return None


# ---------------------------------------------------------------------
# 2) Process the Teva pipeline HTML, returning a list of MasterTable dicts
# ---------------------------------------------------------------------
async def process_teva_html(html_content):
    """
    Parses the Teva pipeline HTML and returns a list of serialized MasterTable objects (dicts).
    - Uses dynamic color map from the pipeline legend
    - Extracts date_last_updated
    - Splits multiple indications
    - Gathers 'partner' text from <p> if "In collaboration with" is found
    - Ensures we produce a MasterTable record for each indication
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Teva pipeline.")
            # Optionally send an SMS if we get empty content
            send_sms(
                phone_number="9144334333",
                message="Teva script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        results = []
        processed_treatments = set()   # to avoid duplicates if needed

        # ---------------------------------------------------------------------
        # A) Grab date_last_updated from the blockquote area
        #    e.g. "Pipeline is current as of November 1, 2024."
        # ---------------------------------------------------------------------
        date_last_updated = None
        date_block = soup.select_one(
            "div.vi-typesystem.vi-typesystem--article.vi-typesystem--blockquote.vi-typesystem--collapse-last p strong"
        )
        if date_block:
            date_last_updated = date_block.get_text(strip=True)

        # Turn date_last_updated into a MultilingualDataCollection
        date_last_updated_translator = MultilingualData()
        if date_last_updated:
            date_last_updated_translator.add_translation("en", date_last_updated)
        else:
            date_last_updated_translator.add_translation("en", "Null")

        date_last_updated_collection = MultilingualDataCollection()
        date_last_updated_collection.add_data(date_last_updated_translator)

        # ---------------------------------------------------------------------
        # B) Dynamically build the color_map from the <ul class="vi-rd-pipeline-legend">
        #    e.g.  --vi-accordion-pipeline-base-color: #00a03b  => "Novel Biologics"
        # ---------------------------------------------------------------------
        color_map = {}
        legend_items = soup.select("ul.vi-rd-pipeline-legend li.vi-rd-pipeline-legend__item")
        for li in legend_items:
            style_attr = li.get("style", "")
            match_color = re.search(r"--vi-accordion-pipeline-base-color:\s?([^;]+)", style_attr, re.IGNORECASE)
            if match_color:
                color_code = match_color.group(1).strip().lower()
                color_label = li.get_text(strip=True)
                color_map[color_code] = color_label

        # ---------------------------------------------------------------------
        # C) Find each phase block: <div class="pipeline-phase-js">
        #    The phase heading is typically <h3 class="mt-60"> => "Phase 2", etc.
        # ---------------------------------------------------------------------
        all_phase_sections = soup.select(".pipeline-phase-js")

        for phase_section in all_phase_sections:
            # Phase name
            phase_header = phase_section.select_one("h3.mt-60")
            if not phase_header:
                continue
            raw_phase_text = phase_header.get_text(strip=True)
            # Clean the phase name if you have a custom logic
            phase_str = clean_phase(raw_phase_text) if raw_phase_text else "Null"

            # Build phase collection
            phase_translator = MultilingualData()
            phase_translator.add_translation("en", phase_str)
            phase_collection = MultilingualDataCollection()
            phase_collection.add_data(phase_translator)

            # -----------------------------------------------------------------
            # D) For each drug item: <div class="vi-accordion-pipeline__item">
            # -----------------------------------------------------------------
            drug_items = phase_section.select(".vi-accordion-pipeline__item")
            for item in drug_items:
                # 1) Pull the color code => therapeutic_area from color_map
                style_attr = item.get("style", "")
                match_color = re.search(r"--vi-accordion-pipeline-base-color:\s?([^;]+)", style_attr, re.IGNORECASE)
                if match_color:
                    color_code = match_color.group(1).strip().lower()
                else:
                    color_code = None

                therapeutic_area_raw = color_map.get(color_code, "Null")

                # Build therapeutic_area collection
                therapeutic_area_translator = MultilingualData()
                therapeutic_area_translator.add_translation("en", clean_text(therapeutic_area_raw))
                therapeutic_area_collection = MultilingualDataCollection()
                therapeutic_area_collection.add_data(therapeutic_area_translator)

                # 2) Drug name => h4.vi-accordion-pipeline__title
                title_el = item.select_one("h4.vi-accordion-pipeline__title")
                drug_name_raw = title_el.get_text(strip=True) if title_el else None
                drug_name = clean_text(drug_name_raw) if drug_name_raw else "Null"

                # Build drug_name collection
                drug_name_translator = MultilingualData()
                drug_name_translator.add_translation("en", drug_name)
                drug_name_collection = MultilingualDataCollection()
                drug_name_collection.add_data(drug_name_translator)

                # 3) Treatment alias => span.vi-accordion-pipeline__subtitle
                subtitle_el = item.select_one("span.vi-accordion-pipeline__subtitle")
                treatment_alias_raw = subtitle_el.get_text(strip=True) if subtitle_el else None
                treatment_alias = clean_text(treatment_alias_raw) if treatment_alias_raw else "Null"

                treatment_alias_translator = MultilingualData()
                treatment_alias_translator.add_translation("en", treatment_alias)
                treatment_alias_collection = MultilingualDataCollection()
                treatment_alias_collection.add_data(treatment_alias_translator)

                # 4) <li> tags => project_type (first li) + subsequent li => indications
                li_tags = item.select("ul.vi-accordion-pipeline__tags li")
                if not li_tags:
                    project_type_raw = None
                    indications_list = []
                else:
                    project_type_raw = li_tags[0].get_text(strip=True) if li_tags else None
                    project_type_raw = clean_text(project_type_raw) if project_type_raw else "Null"

                    indications_list = []
                    # subsequent li tags => e.g. "Ulcerative Colitis, Crohn’s Disease"
                    for li_tag in li_tags[1:]:
                        raw_indications = li_tag.get_text(strip=True)
                        if not raw_indications:
                            continue
                        # Split by comma if multiple
                        for single_indication in raw_indications.split(","):
                            indications_list.append(single_indication.strip())

                # Build project_type as a string or a MultiLingualData if you prefer
                # For now let's keep it simple as a string in "notes" or store in MasterTable
                project_type_str = project_type_raw if project_type_raw else "Null"

                # 5) Partner => if there's <p> with "In collaboration with ...", store in notes
                partner_text = None
                p_tag = item.select_one(".vi-accordion-pipeline__content p")
                if p_tag:
                    p_text = p_tag.get_text(strip=True)
                    partner_text = clean_text(p_text)

                # We'll store partner_text in the notes field or directly in the MasterTable
                # Let's store it in a separate notes translator
                notes_translator = MultilingualData()
                if partner_text:
                    notes_translator.add_translation("en", partner_text)
                else:
                    notes_translator.add_translation("en", "Null")
                notes_collection = MultilingualDataCollection()
                notes_collection.add_data(notes_translator)

                # Build a translator for the project type if you want:
                project_type_translator = MultilingualData()
                project_type_translator.add_translation("en", project_type_str)
                project_type_collection = MultilingualDataCollection()
                project_type_collection.add_data(project_type_translator)

                # date_scraped is "now" in UTC
                date_scraped = datetime.now(timezone.utc)

                # -----------------------------------------------------------------
                # E) Create a MasterTable record for each indication
                # -----------------------------------------------------------------
                if not indications_list:
                    # If no indications => create one record with indication="Null"
                    single_indication = "Null"

                    # Build indication translator
                    indication_translator = MultilingualData()
                    indication_translator.add_translation("en", single_indication)
                    indication_collection = MultilingualDataCollection()
                    indication_collection.add_data(indication_translator)

                    # Generate identification key
                    identification_key = generate_identification_key(
                        "Teva",
                        drug_name,
                        single_indication,
                        partner_text
                    )

                    # Check for duplicates
                    unique_key = (drug_name, single_indication, phase_str, partner_text)
                    if unique_key not in processed_treatments:
                        processed_treatments.add(unique_key)

                        master_record = MasterTable(
                            company_name="Teva",
                            treatment_name=drug_name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            identification_key=identification_key,
                            date_scraped=date_scraped,
                            date_last_changed=date_last_updated_collection.get_collection_as_json(),
                            partner=notes_collection.get_collection_as_json(),
                            # You can store project_type if your MasterTable has it:
                            project_type=project_type_collection.get_collection_as_json(),
                            # Or store the alias as well:
                            treatment_alias=treatment_alias_collection.get_collection_as_json()
                        )
                        results.append(master_record.__dict__)

                else:
                    # For each indication in indications_list
                    for indication_raw in indications_list:
                        if not indication_raw:
                            indication_raw = "Null"
                        indication_clean = clean_text(indication_raw)

                        # Build indication translator
                        indication_translator = MultilingualData()
                        indication_translator.add_translation("en", indication_clean)
                        indication_collection = MultilingualDataCollection()
                        indication_collection.add_data(indication_translator)

                        # Generate identification key
                        identification_key = generate_identification_key(
                            "Teva",
                            drug_name,
                            indication_clean
                        )

                        # Check for duplicates
                        unique_key = (drug_name, indication_clean, phase_str, partner_text)
                        if unique_key in processed_treatments:
                            continue
                        processed_treatments.add(unique_key)

                        master_record = MasterTable(
                            company_name="Teva",
                            treatment_name=drug_name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            identification_key=identification_key,
                            date_scraped=date_scraped,
                            date_last_changed=date_last_updated_collection.get_collection_as_json(),
                            partner=notes_collection.get_collection_as_json(),
                            project_type=project_type_collection.get_collection_as_json(),
                            treatment_alias=treatment_alias_collection.get_collection_as_json()
                        )
                        results.append(master_record.__dict__)

        logging.info(f"Processed {len(results)} treatments for Teva pipeline.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Teva's Pipeline: {e}")
        # Optionally send an SMS containing the error
        send_sms(
            phone_number="9144334333",
            message=f"Error in Teva script: {e}. Please investigate!"
        )
        return []
