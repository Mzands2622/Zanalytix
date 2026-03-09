from function_app import (
    fetch_with_zyte,
    clean_phase,
    clean_text,
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


# -------------
# Helper Functions
# -------------
def map_class_to_percent(class_list):
    """
    Return an integer width approximation based on the container's class name.
    Example:
      "progress-bar-containerA" => 69
      "progress-bar-containerB" => 57
      "progress-bar-containerC" => 48
    """
    # Convert to a set so we can do quick membership checks
    class_set = set(class_list)

    if "progress-bar-containerA" in class_set:
        return 69
    elif "progress-bar-containerB" in class_set:
        return 57
    elif "progress-bar-containerC" in class_set:
        return 48
    # If none matched, default to zero (unknown).
    return 0


def map_percent_to_phase(percent):
    """
    Convert numeric width (approx) to textual phase label.
    Adjust thresholds as you see fit. Example below:
    """
    if percent >= 65:
        return "Phase 3"
    elif 55 <= percent < 65:
        return "Phase 2"
    elif 40 <= percent < 55:
        return "Phase 1"
    elif 30 <= percent < 40:
        return "Preclinical"
    # Fallback
    return "Unknown"


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_zydus_html():
    """
    Returns the Zydus pipeline URL (same as your original snippet).
    """
    try:
        url = "https://zydustx.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Zydus pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_zydus_html(html_content):
    """
    Parses the HTML and returns a list of serialized MasterTable objects.
    Now uses class-based logic to detect the phase.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Zydus pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Zydus script returned no HTML content. Please investigate!"
            )
            return []

        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')

        # These sections hold the final pipeline lines for each product
        # i.e. "Saroglitazar in Primary Biliary Cholangitis," etc.
        pipeline_sections = soup.find_all('div', class_='mobile_pipeline')

        treatments = []
        processed_treatments = set()

        for section in pipeline_sections:
            # 1) Identify the pipeline name (drug + condition)
            name_div = section.find('div', class_='pipeline_name')
            if not name_div:
                continue

            full_title = name_div.get_text(strip=True)

            # 2) Identify the container div for progress bar, e.g.:
            #    <div class="progress-bar-containerA progress_container">
            container_div = section.find("div", class_="progress_container")
            if container_div:
                class_list = container_div.get("class", [])
                pct = map_class_to_percent(class_list)  # e.g. 69
                phase = map_percent_to_phase(pct)       # e.g. "Phase 3"
            else:
                phase = "Unknown"

            # 3) Break out the text into treatment_name vs. therapeutic_area
            if " in " in full_title:
                treatment_name, therapeutic_area = full_title.split(" in ", 1)
            else:
                treatment_name = full_title
                therapeutic_area = "Unknown"

            # Cleanup text
            treatment_name = clean_text(treatment_name.strip())
            therapeutic_area = clean_text(therapeutic_area.strip())

            # 4) Build unique ID, date, translations, etc.
            identification_key = generate_identification_key(
                "Zydustx", treatment_name, therapeutic_area
            )
            date_scraped = datetime.now(timezone.utc)

            therapeutic_area_translator = MultilingualData()
            therapeutic_area_translator.add_translation("en", therapeutic_area)

            name_translator = MultilingualData()
            name_translator.add_translation("en", treatment_name)

            phase_translator = MultilingualData()
            phase_translator.add_translation("en", phase)

            therapeutic_area_collection = MultilingualDataCollection()
            therapeutic_area_collection.add_data(therapeutic_area_translator)

            name_collection = MultilingualDataCollection()
            name_collection.add_data(name_translator)

            phase_collection = MultilingualDataCollection()
            phase_collection.add_data(phase_translator)

            treatment_key = (treatment_name, therapeutic_area, phase)
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Zydus Pharmaceuticals",
                    treatment_name=name_collection.get_collection_as_json(),
                    therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    identification_key=identification_key,
                    date_scraped=date_scraped,
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Zydustx.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Zydus Pharmaceuticals' Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Zydus Pharmaceuticals script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
