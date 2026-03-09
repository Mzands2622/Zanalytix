# iovance_pipeline.py

import re
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these to match your project structure:
from function_app import (
    fetch_with_zyte,  # the same function or a shared version
    clean_text,
    clean_phase,  # or keep your custom get_phase logic
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)


def get_phase(style_attr, study_text):
    """
    Heuristic to guess the phase from the pipeline-capsule's style or text.
    (Same logic as your original script.)
    """
    lower_study = study_text.lower()
    if "phase 3" in lower_study:
        return "Phase 3"
    elif "phase 2" in lower_study:
        return "Phase 2"
    elif "phase 1" in lower_study:
        return "Phase 1"

    # Otherwise, parse the width style for e.g. 'width: 50%'
    width_match = re.search(r'width:\s*([\d.]+)%', style_attr)
    if width_match:
        width_val = float(width_match.group(1))
        if width_val >= 90:
            return "Pivotal"
        elif width_val >= 60:
            return "Phase 2"
        elif width_val >= 30:
            return "Phase 1"
        else:
            return "IND-Enabling"
    return ""


def parse_footnotes(soup):
    """
    Locate the footnote paragraph and build a dict of key -> definition.
    E.g.: "1L=first line; 2L=second line" becomes {"1L": "first line", "2L": "second line"}.
    """
    footnotes_map = {}
    footnote_paragraph = soup.find("p", class_="footnote")
    if not footnote_paragraph:
        return footnotes_map

    # Extract raw text
    footnote_text = footnote_paragraph.get_text(strip=True)
    # Split on semicolons; each chunk should be 'key=value'
    pairs = [chunk.strip() for chunk in footnote_text.split(';') if chunk.strip()]

    for pair in pairs:
        if '=' in pair:
            key, definition = pair.split('=', 1)
            key = key.strip()
            definition = definition.strip()
            footnotes_map[key] = definition

    return footnotes_map


def parse_iovance_pipeline_html(html_content):
    """
    Low-level parsing of Iovance pipeline from raw HTML.
    Returns a list of dicts with keys:
      therapeutic_area, treatment_name, indication, study, phase, notes
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    # 1) Parse out the footnotes once
    footnotes_map = parse_footnotes(soup)

    all_results = []
    pipeline_sections = soup.find_all("div", class_="pipeline-items")

    for section in pipeline_sections:
        # The therapeutic area is in the pipeline-head
        head_div = section.find("div", class_="pipeline-head")
        if not head_div:
            continue
        raw_therapeutic_area = head_div.get_text(strip=True)

        # The actual drug rows are in pipeline-body -> pipeline-body-items
        body = section.find("div", class_="pipeline-body")
        if not body:
            continue

        items = body.find_all("div", class_="pipeline-body-items", recursive=False)
        for item in items:
            treatment_div = item.find("div", class_="col1")
            indication_div = item.find("div", class_="col2")
            capsule_div = item.find("div", class_="pipeline-capsule")

            if not treatment_div or not indication_div or not capsule_div:
                continue

            raw_treatment_name = treatment_div.get_text(strip=True)
            raw_indication = indication_div.get_text(strip=True)

            study_span = capsule_div.find("span", class_="text-1")
            notes_span = capsule_div.find("span", class_="text-2")

            raw_study = study_span.get_text(strip=True) if study_span else ""
            # Start notes as a list (some items come from the raw HTML notes)
            raw_notes_list = [notes_span.get_text(strip=True)] if notes_span else []

            # Determine phase
            style_attr = capsule_div.get("style", "")
            raw_phase = get_phase(style_attr, raw_study)

            # Check footnotes for relevant abbreviations in the row's text
            row_text_combined = f"{raw_treatment_name} {raw_indication} {raw_study}".lower()

            # Use a set to avoid duplicates
            notes_set = set(raw_notes_list)
            for abbrev, definition in footnotes_map.items():
                if abbrev.lower() in row_text_combined:
                    notes_set.add(definition)

            # Filter out empty strings
            final_notes_list = [n for n in notes_set if n]

            row_data = {
                "therapeutic_area": raw_therapeutic_area,
                "treatment_name": raw_treatment_name,
                "indication": raw_indication,
                "study": raw_study,
                "phase": raw_phase,
                "notes": final_notes_list,
            }
            all_results.append(row_data)

    return all_results


async def process_iovance_html(html_content):
    """
    Parses Iovance pipeline HTML, cleans & logs, builds MasterTable objects.
    Identification key = (treatment_name, indication, therapeutic_area).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Iovance pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Iovance script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_iovance_pipeline_html(html_content)
        if not raw_data:
            logging.warning("No pipeline data found in Iovance HTML.")
            send_sms(
                phone_number="9144334333",
                message="Iovance script found no pipeline data. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for item in raw_data:
            raw_therapeutic_area = item.get("therapeutic_area", "")
            raw_treatment_name = item.get("treatment_name", "")
            raw_indication = item.get("indication", "")
            raw_study = item.get("study", "")
            raw_phase = item.get("phase", "")
            raw_notes_list = item.get("notes", [])

            # Convert notes to a single multiline string
            combined_notes = "\n".join(raw_notes_list) if raw_notes_list else ""

            # Clean text
            therapeutic_area = clean_text(raw_therapeutic_area)
            treatment_name = clean_text(raw_treatment_name)
            indication = clean_text(raw_indication)
            study = clean_text(raw_study)
            # If you want to unify phases with your standard approach:
            # phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)
            notes = clean_text(combined_notes)

            # Generate identification key with (treatment_name, indication, therapeutic_area)
            identification_key = generate_identification_key(
                "Iovance",
                treatment_name,
                indication,
                therapeutic_area
            )

            # Build multilingual data
            therapeutic_trans = MultilingualData()
            treatment_trans = MultilingualData()
            indication_trans = MultilingualData()
            study_trans = MultilingualData()
            phase_trans = MultilingualData()
            notes_trans = MultilingualData()

            therapeutic_trans.add_translation("en", therapeutic_area)
            treatment_trans.add_translation("en", treatment_name)
            indication_trans.add_translation("en", indication)
            study_trans.add_translation("en", study)
            phase_trans.add_translation("en", phase)
            notes_trans.add_translation("en", notes)

            therapeutic_coll = MultilingualDataCollection()
            treatment_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            study_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            therapeutic_coll.add_data(therapeutic_trans)
            treatment_coll.add_data(treatment_trans)
            indication_coll.add_data(indication_trans)
            study_coll.add_data(study_trans)
            phase_coll.add_data(phase_trans)
            notes_coll.add_data(notes_trans)

            # Prepare a uniqueness key
            record_key = (
                therapeutic_area, 
                treatment_name,
                indication, 
                study, 
                phase, 
                notes
            )
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Iovance Biotherapeutics",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    # Fields
                    therapeutic_area=therapeutic_coll.get_collection_as_json(),
                    treatment_name=treatment_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    study=study_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Iovance.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Iovance's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Iovance script: {e}. Please investigate!"
        )
        return []


async def fetch_iovance_html():
    """
    Fetches the Iovance pipeline page via Zyte.
    """
    try:
        url = "https://www.iovance.com/clinical-pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Iovance HTML: {e}")
        return None

