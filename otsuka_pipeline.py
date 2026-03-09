import logging
import asyncio
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# These imports are from your custom app/module:
from function_app import (
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    fetch_with_zyte,
    send_sms
)

# ------------------------------------------------
# 1) Fetch the Otsuka Pipeline HTML via Zyte
# ------------------------------------------------
async def fetch_otsuka_html():
    """
    Fetches the Otsuka pipeline page HTML via Zyte API
    and returns the HTML content as a string.
    """
    try:
        url = "https://www.otsuka.co.jp/en/research-and-development/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Otsuka HTML: {e}", exc_info=True)
        return None


# ------------------------------------------------
# 2) Process / Parse the HTML
# ------------------------------------------------
async def process_otsuka_html(html_content):
    """
    Parses Otsuka's pipeline HTML content. 
    Returns a list of dictionaries corresponding to MasterTable records.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Otsuka pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Otsuka script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')

         # --------------------------------------
        # CAPTURE DATE LAST UPDATED (if present)
        # e.g. <p class="pipeline-date">(as of September 30, 2024)</p>
        # --------------------------------------
        date_last_updated = None
        date_paragraph = soup.find("p", class_="pipeline-date")
        if date_paragraph:
            text_content = date_paragraph.get_text(strip=True)
            match_parenthetical = re.search(r"\(as of ([^)]+)\)", text_content, re.IGNORECASE)
            if match_parenthetical:
                # This extracts only what's inside the parentheses after 'as of'
                date_last_updated = match_parenthetical.group(1)
                # e.g. "September 30, 2024"

        # Each pipeline item is in <div class="pipeline-table__item js-accordion">
        items = soup.select("div.pipeline-table__item.js-accordion")
        if not items:
            logging.warning("No pipeline items found on Otsuka page.")
            return []

        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # Iterate over each pipeline item
        for item in items:
            # This sub-block has the "5 columns" data we want
            data_section = item.select_one("div.pipeline-table__item__data")
            if not data_section:
                continue

            code_cell = data_section.select_one("div.pipeline-table__cell--code")
            name_cell = data_section.select_one("div.pipeline-table__cell--name")
            disease_cell = data_section.select_one("div.pipeline-table__cell--disease")
            country_cell = data_section.select_one("div.pipeline-table__cell--country")
            phase_cell = data_section.select_one("div.pipeline-table__cell--phase")

            code = clean_text(code_cell.get_text(strip=True) if code_cell else "")
            generic_name = clean_text(name_cell.get_text(strip=True) if name_cell else "")
            disease = clean_text(disease_cell.get_text(strip=True) if disease_cell else "")
            country = clean_text(country_cell.get_text(strip=True) if country_cell else "")
            phase = clean_phase(phase_cell.get_text(strip=True) if phase_cell else "")

            # Detail text is in <div class="pipeline-table__item__detail js-accordion__panel">
            detail_section = item.select_one("div.pipeline-table__item__detail.js-accordion__panel")
            if detail_section:
                detail_inner_p = detail_section.select_one("div.pipeline-table__item__detail__inner p")
                detail_text = clean_text(detail_inner_p.get_text(strip=True) if detail_inner_p else "")
            else:
                detail_text = ""

            # We can require certain fields to be present.
            # For example, if any of these are crucial, decide whether to skip or not:
            if not any([generic_name, code]):
                logging.warning("Skipping item with no name or code.")
                continue

            # identification_key (company + code + disease + phase is often unique enough)
            identification_key = generate_identification_key("Otsuka", code, disease, generic_name, country)

            # Prepare our multilingual fields
            disease_trans = MultilingualData()
            disease_trans.add_translation("en", disease)

            generic_name_trans = MultilingualData()
            generic_name_trans.add_translation("en", generic_name)

            detail_trans = MultilingualData()
            detail_trans.add_translation("en", detail_text)

            country_trans = MultilingualData()
            country_trans.add_translation("en", country)

            name_trans = MultilingualData()
            name_trans.add_translation("en", code)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            date_updated_trans = MultilingualData()
            date_updated_trans.add_translation("en", date_last_updated)

            # Create collections
            disease_collection = MultilingualDataCollection()
            disease_collection.add_data(disease_trans)

            generic_name_collection = MultilingualDataCollection()
            generic_name_collection.add_data(generic_name_trans)

            detail_collection = MultilingualDataCollection()
            detail_collection.add_data(detail_trans)

            country_collection = MultilingualDataCollection()
            country_collection.add_data(country_trans)

            name_collection = MultilingualDataCollection()
            name_collection.add_data(name_trans)

            phase_collection = MultilingualDataCollection()
            phase_collection.add_data(phase_trans)

            date_updated_collection = MultilingualDataCollection()
            date_updated_collection.add_data(date_updated_trans)


            # Unique key to avoid duplicates (in case they appear in the table)
            treatment_key = (disease, generic_name, phase, code, country, detail_text)
            if treatment_key not in processed_treatments:
                # Build our MasterTable record
                master_record = MasterTable(
                    company_name="Otsuka",
                    # Some fields from your MasterTable model:
                    treatment_name=name_collection.get_collection_as_json(),  # or code + generic_name if you prefer
                    generic_name=generic_name_collection.get_collection_as_json(),
                    indication=disease_collection.get_collection_as_json(),
                    country=country_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    notes=detail_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    date_last_changed=date_updated_collection.get_collection_as_json()
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Otsuka.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Otsuka's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Otsuka script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []