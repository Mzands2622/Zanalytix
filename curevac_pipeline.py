# curevac_pipeline.py

import re
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Assuming these come from your shared function_app
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # If you want to unify your phase logic, or keep map_phase_by_class separately
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

async def fetch_curevac_html():
    """
    Fetches the CureVac pipeline page via Zyte.
    """
    try:
        url = "https://www.curevac.com/en/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching CureVac HTML: {e}")
        return None

def map_phase_by_class(classes):
    """
    Maps CureVac's progress bar classes (ppl-progssbar-p1, -p2, -precl, etc.)
    to a textual Phase label.
    """
    # classes is typically a list of class names
    if any("ppl-progssbar-p3" in c for c in classes):
        return "Phase 3"
    elif any("ppl-progssbar-p2" in c for c in classes):
        return "Phase 2"
    elif any("ppl-progssbar-p1" in c for c in classes):
        return "Phase 1"
    elif any("ppl-progssbar-precl" in c for c in classes):
        return "Preclinical"
    return "Unknown"

async def process_curevac_html(html_content):
    """
    Parses the CureVac pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for CureVac pipeline.")
            send_sms(
                phone_number="9144334333",
                message="CureVac script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Select only top-level .vc_row (exclude .row-inner)
        top_rows = soup.select("div.vc_row.row-container:not(.row-inner)")
        if not top_rows:
            logging.warning("No top-level .vc_row elements found in CureVac HTML.")
            send_sms(
                phone_number="9144334333",
                message="CureVac script found no pipeline rows. Please investigate!"
            )
            return []

        current_area = ""
        results = []
        processed_entries = set()

        for row in top_rows:
            # Check for area heading in <h2 class="h2 text-color-prif-color">
            area_heading = row.select_one("h2.h2.text-color-prif-color")
            if area_heading:
                current_area = area_heading.get_text(strip=True)

            # Progress bar => indicates a pipeline entry
            progress_bar = row.select_one("div.vc_progress_bar")
            if not progress_bar:
                continue

            # ------------------------------------------
            # 2) Extract "indication" & "treatment_name"
            # ------------------------------------------
            pipeline_h2 = row.select_one("h2:not(.text-color-prif-color)")
            raw_indication = ""
            if pipeline_h2:
                raw_indication = pipeline_h2.get_text(strip=True)

            # If not found, try <h5>
            if not raw_indication:
                h5_for_indication = row.select_one("h5")
                if h5_for_indication:
                    raw_indication = h5_for_indication.get_text(strip=True)

            # Potential second heading for treatment name
            raw_treatment_name = ""
            if pipeline_h2:
                # We used <h2> for indication, let's see if there's an <h5> for treatment
                h5_el = row.select_one("h5")
                if h5_el and (raw_indication != h5_el.get_text(strip=True)):
                    raw_treatment_name = h5_el.get_text(strip=True)

            # If both are empty, skip this
            if not raw_indication and not raw_treatment_name:
                continue

            # ------------------------------------------
            # 3) Determine phase from progress bar classes
            # ------------------------------------------
            classes = progress_bar.get("class", [])
            raw_phase = map_phase_by_class(classes)

            # ------------------------------------------
            # 4) Partner detection => "Fully licensed to"
            # ------------------------------------------
            raw_partner = ""
            licensed_block = row.find(string=re.compile(r"Fully licen[cs]ed to", re.IGNORECASE))
            if licensed_block:
                partner_img = licensed_block.find_next("img")
                if partner_img:
                    # Save the src attribute as the partner ID
                    raw_partner = partner_img.get("src", "").strip()
                else:
                    # Otherwise use the text after "to"
                    after_text = licensed_block.split("to", 1)[-1].strip()
                    raw_partner = after_text

            # ------------------------------------------
            # 5) Notes & study data from panel-body
            # ------------------------------------------
            notes = []
            raw_study = ""
            details_panel = row.select_one("div.panel-body.wpb_accordion_content")
            if details_panel:
                paragraphs = details_panel.select("p")
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    link = p.select_one("a[href*='clinicaltrials.gov']")
                    if link:
                        study_id = link.get_text(strip=True)
                        study_href = link["href"]
                        raw_study = f"{study_id} - {study_href}"
                    else:
                        notes.append(text)

            raw_notes = "\n".join(notes)

            # ------------------------------------------
            # 6) Clean text fields
            # ------------------------------------------
            therapeutic_area = clean_text(current_area)
            indication = clean_text(raw_indication)
            treatment_name = clean_text(raw_treatment_name)
            phase = clean_phase(raw_phase)
            partner = clean_text(raw_partner)
            notes_str = clean_text(raw_notes)
            study_str = clean_text(raw_study)

            # ------------------------------------------
            # 7) Validate required fields (if needed)
            # ------------------------------------------
            if not indication and not treatment_name:
                logging.warning("Skipping CureVac entry due to missing key components.")
                continue

            # ------------------------------------------
            # 8) Generate identification key
            # ------------------------------------------
            identification_key = generate_identification_key(
                "CureVac",
                treatment_name,
                indication,
                therapeutic_area
            )

            # ------------------------------------------
            # 9) Build multilingual data
            # ------------------------------------------
            area_translator = MultilingualData()
            indication_translator = MultilingualData()
            treatment_translator = MultilingualData()
            phase_translator = MultilingualData()
            partner_translator = MultilingualData()
            notes_translator = MultilingualData()
            study_translator = MultilingualData()

            # Add the English translations
            area_translator.add_translation("en", therapeutic_area)
            indication_translator.add_translation("en", indication)
            treatment_translator.add_translation("en", treatment_name)
            phase_translator.add_translation("en", phase)
            partner_translator.add_translation("en", partner)
            notes_translator.add_translation("en", notes_str)
            study_translator.add_translation("en", study_str)

            # Wrap each in a MultilingualDataCollection
            area_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            treatment_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()

            area_collection.add_data(area_translator)
            indication_collection.add_data(indication_translator)
            treatment_collection.add_data(treatment_translator)
            phase_collection.add_data(phase_translator)
            partner_collection.add_data(partner_translator)
            notes_collection.add_data(notes_translator)
            study_collection.add_data(study_translator)

            # ------------------------------------------
            # 10) Create MasterTable record
            # ------------------------------------------
            record_key = (therapeutic_area, indication, treatment_name, phase, partner, study_str)
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="CureVac",
                    therapeutic_area=area_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    treatment_name=treatment_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    study=study_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key
                )

                # Convert to dict if desired
                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for CureVac.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping CureVac's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in CureVac's script: {e}. Please investigate!"
        )
        return []