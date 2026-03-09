# celltrion_pipeline.py

import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these imports to match your project structure
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # If you want to unify 'Phase' logic or keep your manual mapping
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)


async def fetch_celltrion_html():
    """
    Fetches the Celltrion pipeline page using Zyte.
    """
    try:
        url = "https://www.celltrion.com/en-us/products/pipelines/biologics"
        return url
    except Exception as e:
        logging.error(f"Error fetching Celltrion HTML: {e}")
        return None


def parse_celltrion_pipeline(html_content):
    """
    Parses the raw Celltrion pipeline HTML, extracting the pipeline data fields:
      - treatment_name
      - generic_name
      - indication
      - phase
      - study (list of link URLs)

    Returns a list of dictionaries with these fields.
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    # Locate the relevant part of the HTML
    table_div = soup.select_one('.cpnt_divtable.t-cell4.t-noImg')
    if not table_div:
        print("Could not find the pipeline table.")
        return []

    dl_element = table_div.find('dl', class_='tbody')
    if not dl_element:
        print("Could not find the <dl> containing pipeline rows.")
        return []

    rows = dl_element.find_all('div', recursive=False)
    pipeline_data = []

    for row in rows:
        dt = row.find('dt')
        dds = row.find_all('dd', recursive=False)

        # Safety checks: make sure dt and at least 3 dd's are present
        if not dt or len(dds) < 3:
            continue

        # Extract each field
        t_name_tag = dt.find('span')
        g_name_tag = dds[0].find('span')
        indications_tag = dds[1].find('span')

        treatment_name = t_name_tag.get_text(strip=True) if t_name_tag else ''
        generic_name = g_name_tag.get_text(strip=True) if g_name_tag else ''
        indications_text = indications_tag.get_text(strip=True) if indications_tag else ''

        # Clinical info is in the third dd
        clinical_dd = dds[2]
        link_tags = clinical_dd.find_all('a')
        phase_text = ''
        study_links = []

        # If there's at least one <a> tag, use the first one's text to derive the phase
        if link_tags:
            first_tag = link_tags[0]
            phase_span = first_tag.find('span')
            phase_text_raw = phase_span.get_text(strip=True) if phase_span else ''
            phase_text_lower = phase_text_raw.lower()
            if "phase" in phase_text_lower:
                if "phase 1" in phase_text_lower or "phase1" in phase_text_lower:
                    phase_text = "Phase 1"
                elif "phase 2" in phase_text_lower or "phase2" in phase_text_lower:
                    phase_text = "Phase 2"
                elif "phase 3" in phase_text_lower or "phase3" in phase_text_lower:
                    phase_text = "Phase 3"
                # Add more mappings if necessary.

        # Collect all links in a list
        for tag in link_tags:
            href = tag.get('href', '')
            if href:
                study_links.append(href)

        # Split multiple indications by comma
        split_indications = [ind.strip() for ind in indications_text.split(",") if ind.strip()]

        # Create an entry for each indication
        for indication_val in split_indications:
            pipeline_data.append({
                "treatment_name": treatment_name,
                "generic_name": generic_name,
                "indication": indication_val,
                "phase": phase_text,
                "study": study_links  # list of all study links
            })

    return pipeline_data


async def process_celltrion_html(html_content):
    """
    Processes the Celltrion pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Celltrion pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Celltrion script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_celltrion_pipeline(html_content)
        if not raw_data:
            logging.warning("No pipeline entries found in Celltrion's HTML.")
            send_sms(
                phone_number="9144334333",
                message="Celltrion script found no pipeline data. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for row in raw_data:
            raw_treatment_name = row.get("treatment_name", "")
            raw_generic_name = row.get("generic_name", "")
            raw_indication = row.get("indication", "")
            raw_phase = row.get("phase", "")
            study_links = row.get("study", [])

            # Convert study_links from list to comma-joined string (or keep as multi-lingual notes if you prefer)
            combined_study = ", ".join(study_links) if study_links else ""

            # -----------------------------------------------------
            # 1) Clean fields
            # -----------------------------------------------------
            treatment_name = clean_text(raw_treatment_name)
            generic_name = clean_text(raw_generic_name)
            indication = clean_text(raw_indication)
            # If you want to unify "Phase 1", "Phase 2", "Phase 3", etc. you can do:
            # phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)
            study_text = clean_text(combined_study)

            # -----------------------------------------------------
            # 2) Validate required fields (if any)
            # -----------------------------------------------------
            # For instance, skip if no treatment_name or indication
            if not treatment_name and not indication:
                logging.warning("Skipping Celltrion entry with missing name/indication.")
                continue

            # -----------------------------------------------------
            # 3) Generate identification key
            # -----------------------------------------------------
            identification_key = generate_identification_key(
                "Celltrion",
                treatment_name,
                generic_name,
                indication
            )

            # -----------------------------------------------------
            # 4) Build multilingual data
            # -----------------------------------------------------
            treatment_trans = MultilingualData()
            generic_trans = MultilingualData()
            indication_trans = MultilingualData()
            phase_trans = MultilingualData()
            study_trans = MultilingualData()

            treatment_trans.add_translation("en", treatment_name)
            generic_trans.add_translation("en", generic_name)
            indication_trans.add_translation("en", indication)
            phase_trans.add_translation("en", phase)
            study_trans.add_translation("en", study_text)

            # Wrap in collections
            treatment_coll = MultilingualDataCollection()
            generic_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            study_coll = MultilingualDataCollection()

            treatment_coll.add_data(treatment_trans)
            generic_coll.add_data(generic_trans)
            indication_coll.add_data(indication_trans)
            phase_coll.add_data(phase_trans)
            study_coll.add_data(study_trans)

            # -----------------------------------------------------
            # 5) Create MasterTable record
            # -----------------------------------------------------
            record_key = (treatment_name, generic_name, indication, phase, study_text)
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Celltrion",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    # Additional fields in MasterTable:
                    treatment_name=treatment_coll.get_collection_as_json(),
                    generic_name=generic_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    study=study_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Celltrion.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Celltrion's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Celltrion script: {e}. Please investigate!"
        )
        return []
