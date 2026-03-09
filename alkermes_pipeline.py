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
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import logging
import re

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_alkermes_html():
    """
    Returns the Alkermes pipeline URL.
    """
    try:
        url = "https://www.alkermes.com/research-and-development/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Alkermes pipeline URL: {e}")
        return None

# -----------------------
# Map Percentage to Phase
# -----------------------
def map_percentage_to_phase(num: int) -> str:
    """
    Maps a numeric percentage to a textual pipeline phase.
    """
    if num <= 20:
        return "Discovery"
    elif num <= 40:
        return "Preclinical"
    elif num <= 60:
        return "Phase 1"
    elif num <= 80:
        return "Phase 2"
    else:
        return "Phase 3"


# -----------------------
# Process HTML Function
# -----------------------
async def process_alkermes_html(html_content):
    """
    Parses Alkermes' pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Alkermes pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Alkermes script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_data = []

        # Grab "Last updated: XXX" from the footer
        last_updated = ""
        foot_div = soup.select_one(".foot .fr-view em")
        if foot_div:
            # e.g. "Last updated: December 2024"
            last_updated = foot_div.get_text(strip=True)

        molecule_blocks = soup.select("li.molecule.py-3")
        for m_block in molecule_blocks:
            name_tag = m_block.select_one("p.m-0.pb-4")
            # Clean the molecule name right away
            molecule_name = clean_text(name_tag.get_text(strip=True)) if name_tag else ""

            overview = ""
            clinical_trials = ""
            extra_div = m_block.select_one(".extra")
            if extra_div:
                all_divs = extra_div.find_all("div", recursive=False)
                for d in all_divs:
                    heading = d.select_one("strong")
                    if not heading:
                        continue
                    heading_text = heading.get_text(strip=True).lower()

                    # Instead of just grabbing one <p>, we gather <p> and <li>
                    if "overview" in heading_text:
                        paragraph = d.select_one("p")
                        content_text = paragraph.get_text(" ", strip=True) if paragraph else ""
                        overview = clean_text(content_text)

                    elif "clinical" in heading_text:
                        # NEW LOGIC: gather all <p> and <li>
                        paragraphs_and_li = d.find_all(["p", "li"])
                        combined_text_list = [elem.get_text(" ", strip=True) for elem in paragraphs_and_li]
                        # Join by newline or space, as you prefer
                        content_text = "\n".join(combined_text_list)
                        clinical_trials = clean_text(content_text)

            product_rows = m_block.select("li.product")
            for p_row in product_rows:
                indication_tag = p_row.select_one("p")
                # Clean the indication
                indication_text = clean_text(indication_tag.get_text(strip=True)) if indication_tag else ""

                phase_div = p_row.select_one("div.my-3")
                pipeline_stage = "Unknown"
                if phase_div and "phase-" in phase_div.get("class", [""])[-1]:
                    class_list = phase_div.get("class", [])
                    for c in class_list:
                        if c.startswith("phase-"):
                            try:
                                num_val = int(c.split("-")[-1])
                                # Convert numeric stage -> textual stage -> clean_phase if needed
                                pipeline_stage = clean_phase(map_percentage_to_phase(num_val))
                            except ValueError:
                                pipeline_stage = "Unknown"

                pipeline_data.append({
                    "drug_name": molecule_name,
                    "indication": indication_text,
                    "phase": pipeline_stage,
                    "more_info": overview,
                    "study": clinical_trials,
                })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # Dictionary for "unique_counter" logic
        molecule_counts = {}

        for entry in pipeline_data:
            drug_name = entry["drug_name"]
            indication = entry["indication"]
            phase = entry["phase"]
            more_info = entry["more_info"]
            study = entry["study"]

            # Also clean `last_updated` text before using in translator
            last_updated_clean = clean_text(last_updated)

            # -------------------------
            # Conditional Counter Logic
            # -------------------------
            base_key = (drug_name, indication, more_info, study)

            if base_key not in molecule_counts:
                molecule_counts[base_key] = 1
                unique_id_molecule = drug_name  # first time
            else:
                molecule_counts[base_key] += 1
                suffix_val = molecule_counts[base_key]
                unique_id_molecule = f"{drug_name}-{suffix_val}"

            # -------------------------
            # Generate the identification key
            # -------------------------
            identification_key = generate_identification_key(
                "Alkermes", 
                drug_name,  # <-- Use the suffix version here if you prefer
                indication,
            )

            # Build multilingual fields
            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)

            study_trans = MultilingualData()
            study_trans.add_translation("en", study)

            drug_name_trans = MultilingualData()
            drug_name_trans.add_translation("en", drug_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            date_last_changed_trans = MultilingualData()
            date_last_changed_trans.add_translation("en", last_updated_clean)

            # Add to collections
            indication_collection = MultilingualDataCollection()
            info_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()
            drug_name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            date_last_changed_collection = MultilingualDataCollection()

            indication_collection.add_data(indication_trans)
            info_collection.add_data(info_trans)
            study_collection.add_data(study_trans)
            drug_name_collection.add_data(drug_name_trans)
            phase_collection.add_data(phase_trans)
            date_last_changed_collection.add_data(date_last_changed_trans)

            # Create a unique key for duplicates at the "treatment" level
            treatment_key = (drug_name, indication, phase, more_info, study)

            master_record = MasterTable(
                company_name="Alkermes",
                treatment_name=drug_name_collection.get_collection_as_json(),
                indication=indication_collection.get_collection_as_json(),
                phase=phase_collection.get_collection_as_json(),
                study=study_collection.get_collection_as_json(),
                notes=info_collection.get_collection_as_json(),
                date_scraped=date_scraped,
                identification_key=identification_key,
                date_last_changed=date_last_changed_collection.get_collection_as_json()
            )
            treatments.append(master_record.__dict__)
            processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Alkermes.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Alkermes's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Alkermes script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
