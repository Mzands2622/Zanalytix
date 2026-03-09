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

async def fetch_xbiotech_html():
    """
    Fetches the XBiotech pipeline URL via Zyte.
    """
    try:
        url = "https://www.xbiotech.com/clinical-research"
        return url
    except Exception as e:
        logging.error(f"Error fetching XBiotech HTML: {e}")
        return None

def map_progress_to_phase(progress_percentage):
    progress_value = int(progress_percentage)
    if 0 <= progress_value <= 33:
        return "Phase 1"
    elif 34 <= progress_value <= 66:
        return "Phase 2"
    elif 67 <= progress_value <= 100:
        return "Phase 3"
    return "Unknown Phase"

async def process_xbiotech_html(html_content):
    """
    Parses the XBiotech pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for XBiotech pipeline.")
            send_sms(
                phone_number="9144334333", 
                message="XBiotech script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        treatments = []
        processed_treatments = set()

        # Locate all pipeline rows
        schedule_wrappers = soup.find_all("div", class_="_4-column-schedule-wrapper")
        if not schedule_wrappers:
            logging.warning("No pipeline schedule elements found.")
            send_sms(
                phone_number="9144334333", 
                message="XBiotech script returned no schedule elements. Please investigate!"
            )
            return []

        for wrapper in schedule_wrappers:
            try:
                # ----------------------------------------------------------------
                # 1) Extract raw attributes
                # ----------------------------------------------------------------
                raw_therapeutic_area = wrapper.find("h6").get_text(strip=True) if wrapper.find("h6") else "N/A"
                raw_treatment_name = wrapper.find("p", {"id": lambda x: x and x.startswith("w-node")}).get_text(strip=True) if wrapper.find("p", {"id": lambda x: x and x.startswith("w-node")}) else "N/A"
                raw_indication = wrapper.find_all("p", {"id": lambda x: x and x.startswith("w-node")})[1].get_text(strip=True) if len(wrapper.find_all("p", {"id": lambda x: x and x.startswith("w-node")})) > 1 else "N/A"
                raw_progress = wrapper.find("div", class_="progressbar-con").find("div", class_=lambda x: x and x.startswith("progress-bar-"))

                # Extract progress percentage and map to phase
                progress_percentage = raw_progress.get("class")[0].replace("progress-bar-", "") if raw_progress else "0"
                raw_phase = map_progress_to_phase(progress_percentage)

                # ----------------------------------------------------------------
                # 2) Clean text fields
                # ----------------------------------------------------------------
                therapeutic_area = clean_text(raw_therapeutic_area)
                treatment_name = clean_text(raw_treatment_name)
                indication = clean_text(raw_indication)
                phase = clean_phase(raw_phase)

                # ----------------------------------------------------------------
                # 3) Validate required fields
                # ----------------------------------------------------------------
                if not all([therapeutic_area, treatment_name, indication, phase]):
                    logging.warning("Skipping entry due to missing key components.")
                    continue

                # ----------------------------------------------------------------
                # 4) Generate the identification key
                # ----------------------------------------------------------------
                identification_key = generate_identification_key(
                    "XBiotech",
                    treatment_name,
                    indication,
                    therapeutic_area
                )

                # ----------------------------------------------------------------
                # 5) Build multilingual data objects
                # ----------------------------------------------------------------
                therapeutic_area_translator = MultilingualData()
                indication_translator = MultilingualData()
                treatment_name_translator = MultilingualData()
                phase_translator = MultilingualData()

                therapeutic_area_translator.add_translation("en", therapeutic_area)
                indication_translator.add_translation("en", indication)
                treatment_name_translator.add_translation("en", treatment_name)
                phase_translator.add_translation("en", phase)

                therapeutic_area_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                treatment_name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()

                therapeutic_area_collection.add_data(therapeutic_area_translator)
                indication_collection.add_data(indication_translator)
                treatment_name_collection.add_data(treatment_name_translator)
                phase_collection.add_data(phase_translator)

                # ----------------------------------------------------------------
                # 6) Create MasterTable record
                # ----------------------------------------------------------------
                treatment_key = (therapeutic_area, treatment_name, indication, phase)

                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="XBiotech",
                        therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                        treatment_name=treatment_name_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        date_scraped=datetime.now(timezone.utc),
                        identification_key=identification_key,
                    )

                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(f"Error processing a pipeline entry: {e}")
                continue

        logging.info(f"Processed {len(treatments)} treatments for XBiotech.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping XBiotech's Pipeline: {e}")
        send_sms(
            phone_number="9144334333", 
            message=f"Error in XBiotech's script: {e}. Please investigate!"
        )
        return []