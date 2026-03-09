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


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_uniqure_html():
    """
    Returns the uniQure pipeline URL.
    """
    try:
        url = "https://www.uniqure.com/programs-pipeline/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching uniQure pipeline URL: {e}")
        return None


# -----------------------
# Map Progress to Phase
# -----------------------
def map_progress_to_phase(value: int) -> str:
    """
    Converts a numeric progress bar value to a textual phase.
    """
    if value == 100:
        return "Approved"
    elif value >= 67:
        return "Phase 3"
    elif value >= 34:
        return "Phase 1/2"
    else:
        return "Preclinical"


# -----------------------
# Process HTML Function
# -----------------------
async def process_uniqure_html(html_content):
    """
    Parses uniQure's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for UniQure pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="UniQure script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_data = []

        indication_items = soup.select(".pipeline-body .pipeline-section ul li")
        for item in indication_items:
            partnership = "CSL" if "csl" in item.get("class", []) else "Proprietary"

            h3_tag = item.select_one("h3")
            indication_strong = h3_tag.select_one("strong") if h3_tag else None
            indication = clean_text(indication_strong.get_text(strip=True)) if indication_strong else ""

            drug_label = h3_tag.select_one("span.label") if h3_tag else None
            drug_name = clean_text(drug_label.get_text(strip=True)) if drug_label else ""

            progress_tag = item.select_one("progress")
            phase_value = 0
            if progress_tag and progress_tag.has_attr("value"):
                try:
                    phase_value = int(progress_tag["value"])
                except ValueError:
                    phase_value = 0

            phase_text = clean_phase(map_progress_to_phase(phase_value))

            pipeline_data.append({
                "indication": indication,
                "drug_name": drug_name,
                "phase": phase_text,
                "partnership": partnership
            })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            indication = clean_text(entry["indication"])
            drug_name = clean_text(entry["drug_name"])
            phase = clean_phase(entry["phase"])
            partnership = clean_text(entry["partnership"])

            identification_key = generate_identification_key("uniQure", drug_name, indication, partnership)

            # Multilingual Data
            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            partnership_trans = MultilingualData()
            partnership_trans.add_translation("en", partnership)

            name_trans = MultilingualData()
            name_trans.add_translation("en", drug_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            # Collections
            indication_collection = MultilingualDataCollection()
            partnership_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            indication_collection.add_data(indication_trans)
            partnership_collection.add_data(partnership_trans)
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (indication, drug_name, phase, partnership)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="uniQure",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    partner=partnership_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for uniQure.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping uniQure's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in uniQure script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []