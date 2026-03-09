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
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import logging
import re

def map_phase_to_text(phase_num):
    """
    Maps a phase number to its corresponding text representation.
    """
    phase_mapping = {
        "1": "Phase 1",
        "2": "Phase 2",
        "3": "Phase 3",
        "4": "Phase 4"
    }
    return phase_mapping.get(phase_num, "Unknown")

async def fetch_kyowa_html():
    """
    Fetches the Kyowa Kirin pipeline URL via Zyte.
    """
    try:
        url = "https://www.kyowakirin.com/what_we_do/index.html#anc-pipeline"         
        return url
    except Exception as e:
        logging.error(f"Error fetching Kyowa Kirin HTML: {e}")
        return None

async def process_kyowa_html(html_content):
    """
    Parses the Kyowa Kirin pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Kyowa Kirin pipeline.")
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        treatments = []
        processed_treatments = set()

        # First get the modality mapping
        modality_map = {}
        main_list = soup.select_one("div.pipeline-box-search .inner .content ul.list")
        if main_list:
            list_items = main_list.select('li')
            for li in list_items:
                img_tag = li.select_one('img')
                if not img_tag:
                    continue
                src = img_tag.get("src", "").strip()
                span = li.select_one("span")
                if span:
                    text_node = span.get_text(strip=True)
                    if src and text_node:
                        modality_map[src] = text_node

        # Find pipeline container
        pipeline_container = soup.select_one("div.pipeline-table ul.content")
        if not pipeline_container:
            logging.warning("No pipeline container found.")
            send_sms(
                phone_number="9144334333",
                message="Kyowa Kirin script found no pipeline container. Please investigate!"
            )
            return []

        pipeline_rows = pipeline_container.select("li.contentList")
        
        for row in pipeline_rows:
            # Extract molecule type
            molecule_img = row.select_one('.item.icon img')
            raw_type_of_molecule = ""
            if molecule_img:
                molecule_src = molecule_img.get('src', '').strip()
                raw_type_of_molecule = modality_map.get(molecule_src, molecule_src)

            body_section = row.select_one("ul.itemList._body")
            if not body_section:
                continue

            # Extract main data
            code_name_sel = body_section.select_one(".item.codeName p")
            generic_name_sel = body_section.select_one(".item.genericName p")
            indication_sel = body_section.select_one(".item.indication p")

            raw_treatment_name = code_name_sel.get_text(strip=True) if code_name_sel else ""
            raw_generic_name = generic_name_sel.get_text(strip=True) if generic_name_sel else ""
            raw_indication = indication_sel.get_text(strip=True) if indication_sel else ""

            # Extract phase and notes
            raw_phase = "Unknown"
            raw_notes = ""
            phase_ul = body_section.select_one(".item.phase ul.phaseList")
            if phase_ul:
                all_phase_ps = phase_ul.select("li p")
                if all_phase_ps:
                    last_phase_line = all_phase_ps[-1].get_text(strip=True)
                    match = re.match(r"^(\d+)(?:\s*\((.*)\))?$", last_phase_line)
                    if match:
                        phase_num = match.group(1)
                        raw_phase = map_phase_to_text(phase_num)
                        raw_notes = match.group(2) or ""

            # Extract detail section data
            detail_section = row.select_one("dl.itemList._detail")
            raw_comment = ""
            raw_target = ""
            raw_partner = ""
            raw_study = ""

            if detail_section:
                remarks_dd = detail_section.select_one(".item.remarks dd")
                if remarks_dd:
                    raw_comment = remarks_dd.get_text(strip=True, separator="\n")

                moa_dd = detail_section.select_one(".item.mechanismOfAction dd")
                if moa_dd:
                    raw_target = moa_dd.get_text(strip=True)

                partner_dd = detail_section.select_one(".item.inHouseOrLicensed dd")
                if partner_dd:
                    raw_partner = partner_dd.get_text(strip=True)

                study_dd = detail_section.select_one(".item.clinicalTrialInformation dd")
                if study_dd:
                    raw_study = study_dd.get_text(strip=True)

            # Clean all text fields
            treatment_name = clean_text(raw_treatment_name)
            generic_name = clean_text(raw_generic_name)
            indication = clean_text(raw_indication)
            phase = clean_phase(raw_phase)
            notes = clean_text(raw_notes)
            comment = clean_text(raw_comment)
            target = clean_text(raw_target)
            partner = clean_text(raw_partner)
            study = clean_text(raw_study)
            type_of_molecule = clean_text(raw_type_of_molecule)

            # Generate identification key
            identification_key = generate_identification_key(
                "Kyowa Kirin",
                treatment_name,
                indication
            )

            # Create all multilingual data objects
            treatment_name_translator = MultilingualData()
            generic_name_translator = MultilingualData()
            indication_translator = MultilingualData()
            phase_translator = MultilingualData()
            notes_translator = MultilingualData()
            comment_translator = MultilingualData()
            target_translator = MultilingualData()
            partner_translator = MultilingualData()
            study_translator = MultilingualData()
            type_of_molecule_translator = MultilingualData()

            # Add translations
            treatment_name_translator.add_translation("en", treatment_name)
            generic_name_translator.add_translation("en", generic_name)
            indication_translator.add_translation("en", indication)
            phase_translator.add_translation("en", phase)
            notes_translator.add_translation("en", notes)
            comment_translator.add_translation("en", comment)
            target_translator.add_translation("en", target)
            partner_translator.add_translation("en", partner)
            study_translator.add_translation("en", study)
            type_of_molecule_translator.add_translation("en", type_of_molecule)

            # Create collections
            treatment_name_collection = MultilingualDataCollection()
            generic_name_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            comment_collection = MultilingualDataCollection()
            target_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()
            type_of_molecule_collection = MultilingualDataCollection()

            # Add data to collections
            treatment_name_collection.add_data(treatment_name_translator)
            generic_name_collection.add_data(generic_name_translator)
            indication_collection.add_data(indication_translator)
            phase_collection.add_data(phase_translator)
            notes_collection.add_data(notes_translator)
            comment_collection.add_data(comment_translator)
            target_collection.add_data(target_translator)
            partner_collection.add_data(partner_translator)
            study_collection.add_data(study_translator)
            type_of_molecule_collection.add_data(type_of_molecule_translator)

            # Build unique key for deduplication
            treatment_key = (treatment_name, generic_name, indication, phase)

            # Create MasterTable record if not duplicate
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Kyowa Kirin",
                    treatment_name=treatment_name_collection.get_collection_as_json(),
                    generic_name=generic_name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    comment=comment_collection.get_collection_as_json(),
                    target=target_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    study=study_collection.get_collection_as_json(),
                    type_of_molecule=type_of_molecule_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Kyowa Kirin.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Kyowa Kirin Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Kyowa Kirin script: {e}. Please investigate!"
        )
        return []