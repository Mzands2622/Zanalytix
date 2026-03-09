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

async def fetch_ucb_html():
    try:
        # Fetch HTML using Zyte API
        url = "https://www.ucb.com/innovation/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching UCB HTML: {e}")
        return None

async def process_ucb_html(html_content):
    try:
        if not html_content:
            logging.warning("No HTML content received for UCB pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="UCB script returned no HTML content. Please investigate!"
            )
            return []
            
        treatments = []
        processed_treatments = set()

        # Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_blocks = soup.find_all("div", class_="block medical-preparation")

        if not pipeline_blocks:
            logging.warning("No pipeline blocks found.")
            return []

        for block in pipeline_blocks:
            molecule_div = block.find("div", class_="molecule--medical-preparation")
            molecule_name = clean_text(molecule_div.get_text(strip=True) if molecule_div else "")

            preparation_items = block.find_all("div", class_="medical-preparation-item")

            for prep_item in preparation_items:
                modality_div = prep_item.find("div", class_="modality--medical-preparation")
                modality_text = clean_text(modality_div.get_text(strip=True) if modality_div else "")

                ta_div = prep_item.find("div", class_="therapeutic-area--medical-preparation")
                therapeutic_area = clean_text(ta_div.get_text(strip=True) if ta_div else "")

                ind_div = prep_item.find("div", class_="indication--medical-preparation")
                indication = clean_text(ind_div.get_text(strip=True) if ind_div else "")

                phase_div = prep_item.find("div", class_=re.compile(r"phases--medical-preparation phase-\d+"))
                phase_class = clean_phase("Phase 2" if "phase-52" in phase_div.get("class", []) else "Phase 3" if "phase-78" in phase_div.get("class", []) else "")

                info_div = prep_item.find("div", class_="information--medical-preparation")
                extra_info = clean_text(info_div.get_text(strip=True) if info_div else "")

                # Skip incomplete data
                if not all([therapeutic_area, molecule_name, indication]):
                    logging.warning("Skipping entry due to missing key components.")
                    continue

                # Generate identification key
                identification_key = generate_identification_key("UCB", molecule_name, indication)

                # Create multilingual data
                modality_translator = MultilingualData()
                therapeutic_area_translator = MultilingualData()
                indication_translator = MultilingualData()
                extra_info_translator = MultilingualData()
                name_translator = MultilingualData()
                phase_translator = MultilingualData()

                modality_translator.add_translation("en", modality_text)
                therapeutic_area_translator.add_translation("en", therapeutic_area)
                indication_translator.add_translation("en", indication)
                extra_info_translator.add_translation("en", extra_info)
                name_translator.add_translation("en", molecule_name)
                phase_translator.add_translation("en", phase_class)

                modality_collection = MultilingualDataCollection()
                therapeutic_area_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                extra_info_collection = MultilingualDataCollection()
                name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()

                modality_collection.add_data(modality_translator)
                therapeutic_area_collection.add_data(therapeutic_area_translator)
                indication_collection.add_data(indication_translator)
                extra_info_collection.add_data(extra_info_translator)
                name_collection.add_data(name_translator)
                phase_collection.add_data(phase_translator)

                # Create a unique treatment key
                treatment_key = (therapeutic_area, molecule_name, indication, phase_class)

                # Avoid duplicates
                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="UCB",
                        therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                        treatment_name=name_collection.get_collection_as_json(),
                        modality=modality_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        date_scraped=datetime.now(timezone.utc),
                        identification_key=identification_key,
                        notes=extra_info_collection.get_collection_as_json()
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for UCB.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping UCB's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in UCB script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []