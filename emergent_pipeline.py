# emergent_pipeline.py

import re
import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Adjust these imports according to your project layout:
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # If you want to unify final_phase with this function, or keep your custom mapping
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# Map the count of "dark-blue" squares to a final phase label
PHASE_MAP = {
    0: "Unknown",
    1: "Preclinical",
    2: "Phase 1",
    3: "Phase 2",
    4: "Phase 3"
    # If Emergent extends with more columns, you can add a 5: etc.
}

async def fetch_emergent_html():
    """
    Fetches the Emergent pipeline page via Zyte.
    """
    try:
        url = "https://www.emergentbiosolutions.com/products-services/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Emergent HTML: {e}")
        return None


def parse_emergent_pipeline(html_content):
    """
    Parse Emergent’s pipeline rows from the raw HTML content.

    1) Each row is a .table-row
    2) The left .uk-width-1-2@m has Program name + Description
    3) The right .uk-width-1-2@m has 4 columns for phases:
         Pre Clinical, Phase 1, Phase 2, Phase 3
       Each column is .uk-width-1-5 (or similar). If it’s 'dark-blue',
       that column is completed.
    4) We map the *count* of dark-blue squares => final phase:
         1 => Preclinical
         2 => Phase 1
         3 => Phase 2
         4 => Phase 3
       0 => "Unknown"
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    pipeline_section = soup.select_one('section.pipeline')
    if not pipeline_section:
        print("No <section class='pipeline'> found.")
        return []

    rows = pipeline_section.select('.table-row')
    if not rows:
        print("No .table-row elements found.")
        return []

    pipeline_data = []
    for row in rows:
        half_cols = row.find_all("div", class_=re.compile(r"uk-width-1-2@m"))
        if len(half_cols) < 2:
            continue

        # Left side => program name & comment
        left_side = half_cols[0]
        treatment_name = ""
        comment = ""

        h1_strong = left_side.select_one('h1 strong')
        if h1_strong:
            treatment_name = h1_strong.get_text(strip=True)

        p_tag = left_side.select_one('p')
        if p_tag:
            comment = p_tag.get_text(strip=True)

        # Right side => 4 columns for phases
        right_side = half_cols[1]
        phase_cols = right_side.select('div.uk-width-1-5:not(.show-on-mobile)')

        dark_blue_count = 0
        for col in phase_cols:
            classes = col.get("class", [])
            if "dark-blue" in classes:
                dark_blue_count += 1

        # Lookup the final phase from PHASE_MAP
        final_phase = PHASE_MAP.get(dark_blue_count, "Unknown")

        pipeline_data.append({
            "treatment_name": treatment_name,
            "comment": comment,
            "phase": final_phase
        })

    return pipeline_data


async def process_emergent_html(html_content):
    """
    Parses Emergent pipeline HTML, cleans data, logs errors, returns a list of MasterTable dicts.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Emergent pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Emergent script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_emergent_pipeline(html_content)
        if not raw_data:
            logging.warning("No pipeline rows found in Emergent's HTML.")
            send_sms(
                phone_number="9144334333",
                message="Emergent script found no pipeline rows. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for item in raw_data:
            raw_treatment_name = item.get("treatment_name", "")
            raw_comment = item.get("comment", "")
            raw_phase = item.get("phase", "")  # e.g. "Preclinical", "Phase 1" etc.

            # -----------------------------------------------------
            # 1) Clean the fields
            # -----------------------------------------------------
            treatment_name = clean_text(raw_treatment_name)
            comment = clean_text(raw_comment)
            # If you want to unify "Preclinical" -> "Phase 0" or so, you can use clean_phase here.
            # For now, let's keep the text from PHASE_MAP. Or do:
            # phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)

            # -----------------------------------------------------
            # 3) Generate identification key
            # -----------------------------------------------------
            identification_key = generate_identification_key(
                "Emergent",
                treatment_name,
            )

            # -----------------------------------------------------
            # 4) Build multilingual data
            # -----------------------------------------------------
            treatment_trans = MultilingualData()
            phase_trans = MultilingualData()
            comment_trans = MultilingualData()

            treatment_trans.add_translation("en", treatment_name)
            phase_trans.add_translation("en", phase)
            comment_trans.add_translation("en", comment)

            treatment_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            comment_coll = MultilingualDataCollection()

            treatment_coll.add_data(treatment_trans)
            phase_coll.add_data(phase_trans)
            comment_coll.add_data(comment_trans)

            # -----------------------------------------------------
            # 5) Create MasterTable record
            # -----------------------------------------------------
            record_key = (treatment_name, phase, comment)
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Emergent BioSolutions",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,
                    # If your data model includes these fields:
                    treatment_name=treatment_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    indication=comment_coll.get_collection_as_json(),
                    # If you don't have comment in MasterTable, you can store it as notes instead.
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Emergent.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Emergent's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Emergent's script: {e}. Please investigate!"
        )
        return []