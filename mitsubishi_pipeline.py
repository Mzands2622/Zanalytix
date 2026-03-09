# mitsubishi_pipeline.py

import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adapt these imports to your actual project structure:
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# Map of raw phase text to a more readable form
PHASE_MAP = {
    "Phase1": "Phase 1",
    "Phase2": "Phase 2",
    "Phase3": "Phase 3",
    "Phase1/2": "Phase 1/2",
    "Filed": "Filed"
}


async def fetch_mitsubishi_html():
    """
    Fetch the Mitsubishi pipeline page using Zyte.
    """
    try:
        url = "https://www.mt-pharma.co.jp/e/develop/pipeline.html"
        return url
    except Exception as e:
        logging.error(f"Error fetching Mitsubishi HTML: {e}")
        return None


async def process_mitsubishi_html(html_content):
    """
    Parses the Mitsubishi pipeline HTML, including:
      - date_last_updated from <p class="lead">
      - global notes from <ul class="list list-note"> at the bottom
      - pipeline items from <div class="pipeline-body__item">
    Returns a list of MasterTable objects in dict form.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Mitsubishi pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Mitsubishi script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Grab the date last updated from <p class="lead">
        date_last_updated_tag = soup.find("p", class_="lead")
        raw_date_last_updated = (
            date_last_updated_tag.get_text(strip=True) if date_last_updated_tag else "N/A"
        )

        # 2) Collect "notes" from <ul class="list list-note" ...> (if present)
        raw_notes = ""
        notes_list_tag = soup.select_one('ul.list.list-note[data-parts="typography"]')
        if notes_list_tag:
            # Each <li> has data-parts="typography__elm"
            li_elements = notes_list_tag.select('li[data-parts="typography__elm"]')
            bullet_texts = [li.get_text(strip=True) for li in li_elements]
            raw_notes = "\n".join(bullet_texts)

        # 3) Parse the pipeline items
        pipeline_items = soup.find_all("div", class_="pipeline-body__item")
        if not pipeline_items:
            logging.warning("No pipeline items found in Mitsubishi's HTML.")
            send_sms(
                phone_number="9144334333",
                message="Mitsubishi script found no pipeline items. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for item in pipeline_items:
            # 3a) .pipeline-body__view
            view_block = item.find("div", class_="pipeline-body__view")
            if not view_block:
                continue

            area_elm = view_block.find("div", class_="pipeline-body__view__elm type-area")
            code_elm = view_block.find("div", class_="pipeline-body__view__elm type-code")

            # Indication is the unclassified .pipeline-body__view__elm
            disease_elm = None
            for d in view_block.find_all("div", class_="pipeline-body__view__elm", recursive=False):
                classes = d.get("class", [])
                if classes == ["pipeline-body__view__elm"]:
                    disease_elm = d
                    break

            phase_elm = view_block.find("div", class_="pipeline-body__view__elm type-phase")
            raw_phase = ""
            raw_country = ""

            if phase_elm:
                phase_span = phase_elm.select_one(".pipeline-phase-icon span")
                if phase_span:
                    raw_phase_text = phase_span.get_text(strip=True)
                    raw_phase = PHASE_MAP.get(raw_phase_text, raw_phase_text)

                # Often second .pipeline-body__phase__elm is region/country
                phase_elms = phase_elm.select(".pipeline-body__phase__elm")
                if len(phase_elms) > 1:
                    raw_country = phase_elms[1].get_text(strip=True)

            # 3b) .pipeline-body__hidden
            hidden_block = item.find("div", class_="pipeline-body__hidden")
            desc_map = {}
            if hidden_block:
                desc_dl_list = hidden_block.find_all("dl", class_="pipeline-desc")
                for dl in desc_dl_list:
                    dt = dl.find("dt", class_="pipeline-desc__head")
                    dd = dl.find("dd", class_="pipeline-desc__body")
                    if dt and dd:
                        label = dt.get_text(strip=True)
                        value = dd.get_text(strip=True)
                        desc_map[label] = value

            raw_therapeutic_area = area_elm.get_text(strip=True) if area_elm else ""
            raw_treatment_name = code_elm.get_text(strip=True) if code_elm else ""
            raw_indication = disease_elm.get_text(strip=True) if disease_elm else ""

            raw_brand_name = desc_map.get("Product name", "")
            raw_generic_name = desc_map.get("Generic name", "")
            raw_target = desc_map.get("Mechanism(Indications)", "")
            raw_partner = desc_map.get("Origin/licensee", "")

            # 3c) Clean text fields
            therapeutic_area = clean_text(raw_therapeutic_area)
            treatment_name = clean_text(raw_treatment_name)
            indication = clean_text(raw_indication)
            phase = clean_phase(raw_phase)
            country = clean_text(raw_country)
            brand_name = clean_text(raw_brand_name)
            generic_name = clean_text(raw_generic_name)
            target = clean_text(raw_target)
            partner = clean_text(raw_partner)
            date_last_updated = clean_text(raw_date_last_updated)
            notes = clean_text(raw_notes)

            # 3d) Required fields check (adjust as needed)
            # If you consider indication or treatment_name mandatory, for example:
            if not indication and not treatment_name:
                logging.warning("Skipping entry due to missing indication or treatment name.")
                continue

            # 4) identification key
            identification_key = generate_identification_key(
                "Mitsubishi",
                treatment_name,
                indication,
                country
            )

            # 5) Build multilingual data
            area_trans = MultilingualData()
            treatment_trans = MultilingualData()
            indication_trans = MultilingualData()
            phase_trans = MultilingualData()
            country_trans = MultilingualData()
            brand_trans = MultilingualData()
            generic_trans = MultilingualData()
            target_trans = MultilingualData()
            partner_trans = MultilingualData()
            date_trans = MultilingualData()
            notes_trans = MultilingualData()

            # Add translations (English only for now)
            area_trans.add_translation("en", therapeutic_area)
            treatment_trans.add_translation("en", treatment_name)
            indication_trans.add_translation("en", indication)
            phase_trans.add_translation("en", phase)
            country_trans.add_translation("en", country)
            brand_trans.add_translation("en", brand_name)
            generic_trans.add_translation("en", generic_name)
            target_trans.add_translation("en", target)
            partner_trans.add_translation("en", partner)
            date_trans.add_translation("en", date_last_updated)
            notes_trans.add_translation("en", notes)

            # Wrap in MultilingualDataCollections
            area_coll = MultilingualDataCollection()
            treatment_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            country_coll = MultilingualDataCollection()
            brand_coll = MultilingualDataCollection()
            generic_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            partner_coll = MultilingualDataCollection()
            date_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            area_coll.add_data(area_trans)
            treatment_coll.add_data(treatment_trans)
            indication_coll.add_data(indication_trans)
            phase_coll.add_data(phase_trans)
            country_coll.add_data(country_trans)
            brand_coll.add_data(brand_trans)
            generic_coll.add_data(generic_trans)
            target_coll.add_data(target_trans)
            partner_coll.add_data(partner_trans)
            date_coll.add_data(date_trans)
            notes_coll.add_data(notes_trans)

            # 6) Build the MasterTable record
            record_key = (
                therapeutic_area,
                treatment_name,
                indication,
                phase,
                country,
                brand_name,
                generic_name,
                target,
                partner,
                date_last_updated,
                notes
            )
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Mitsubishi Tanabe Pharma",
                    # Standard fields
                    therapeutic_area=area_coll.get_collection_as_json(),
                    treatment_name=treatment_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    partner=partner_coll.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    # Additional fields
                    brand_name=brand_coll.get_collection_as_json(),
                    generic_name=generic_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    country=country_coll.get_collection_as_json(),
                    date_last_changed=date_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json(),
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Mitsubishi.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Mitsubishi's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Mitsubishi's script: {e}. Please investigate!"
        )
        return []
