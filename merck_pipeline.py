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
import re
import logging

# Function that cleans a string
def clean_text_merck(text):
    text = re.sub(r'[\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_merck_html():
    """
    Fetches the Merck pipeline HTML via Zyte.
    """
    try:
        url = "https://www.merck.com/research/product-pipeline/"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Merck pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_merck_html(html_content):
    """
    Parses the Merck pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Merck pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Merck script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Extract update date
        date_last_changed = "No update date found"
        caption = soup.find('div', class_='pipeline-caption')
        if caption:
            caption_text = caption.text
            match = re.search(r"Updated\s(\w+\s\d+,\s\d{4})", caption_text)
            if match:
                date_last_changed = match.group(1)

        # Process each treatment row
        treatment_rows = soup.find_all('tr', class_='pipeline-program')
        for row in treatment_rows:
            try:
                # Extract program-level data
                molecule_name = clean_text_merck(row.find('h4', class_='pipeline-program-name').text)
                therapeutic_area = clean_text_merck(row.find('div', class_='pipeline-program-t-area').find('span').text)
                mechanism_of_action = clean_text_merck(row.find('div', class_='pipeline-program-content').text)
                modality = clean_text_merck(row.find('div', class_='pipeline-program-modality').find('span').text)

                # Process each indication within the treatment
                indications_data = row.find_all('tr', class_='pipeline-program-indication')
                for indication in indications_data:
                    try:
                        # Extract indication data
                        indication_final = clean_text_merck(
                            indication.find('h6', class_='pipeline-program-indication-title').text)
                        
                        # Determine phase
                        phase_text = ""
                        phase_bars = indication.find('td', class_='phase-bars-table-data')
                        if phase_bars:
                            under_review = phase_bars.find('h6', class_='pipeline-program-indication-title')
                            phase_text = clean_text_merck(
                                under_review.text) if under_review and 'Under review' in under_review.text else ""

                        if not phase_text:
                            phase_bars = indication.find('div', class_='pipeline-phase-bars')
                            if phase_bars:
                                phase_count = len(phase_bars.find_all('div', class_='pipeline-phase-bar active'))
                                phase_text = clean_phase(phase_count) if phase_count > 0 else ""

                        # Final data cleaning
                        molecule_name = clean_text(molecule_name)
                        therapeutic_area = clean_text(therapeutic_area)
                        indication_final = clean_text(indication_final)
                        phase_text = clean_text(phase_text)
                        mechanism_of_action = clean_text(mechanism_of_action)
                        modality = clean_text(modality)

                        # Generate keys
                        identification_key = generate_identification_key("Merck", molecule_name, indication_final, modality)
                        date_scraped = datetime.now(timezone.utc)
                        treatment_key = (
                            molecule_name, therapeutic_area, indication_final, phase_text, mechanism_of_action, modality
                        )

                        # Setup multilingual data
                        therapeutic_area_translator = MultilingualData()
                        indication_area_translator = MultilingualData()
                        mechanism_of_action_translator = MultilingualData()
                        modality_translator = MultilingualData()
                        name_translator = MultilingualData()
                        phase_translator = MultilingualData()
                        date_updated_translator = MultilingualData()

                        therapeutic_area_translator.add_translation("en", therapeutic_area)
                        indication_area_translator.add_translation("en", indication_final)
                        mechanism_of_action_translator.add_translation("en", mechanism_of_action)
                        modality_translator.add_translation("en", modality)
                        name_translator.add_translation("en", molecule_name)
                        phase_translator.add_translation("en", phase_text)
                        date_updated_translator.add_translation("en", date_last_changed)

                        therapeutic_area_collection = MultilingualDataCollection()
                        indication_collection = MultilingualDataCollection()
                        mechanism_of_action_collection = MultilingualDataCollection()
                        modality_collection = MultilingualDataCollection()
                        name_collection = MultilingualDataCollection()
                        phase_collection = MultilingualDataCollection()
                        date_updated_collection = MultilingualDataCollection()

                        therapeutic_area_collection.add_data(therapeutic_area_translator)
                        indication_collection.add_data(indication_area_translator)
                        mechanism_of_action_collection.add_data(mechanism_of_action_translator)
                        modality_collection.add_data(modality_translator)
                        name_collection.add_data(name_translator)
                        phase_collection.add_data(phase_translator)
                        date_updated_collection.add_data(date_updated_translator)

                        # Create master record if not duplicate
                        if treatment_key not in processed_treatments:
                            master_record = MasterTable(
                                company_name="Merck",
                                treatment_name=name_collection.get_collection_as_json(),
                                therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                                indication=indication_collection.get_collection_as_json(),
                                phase=phase_collection.get_collection_as_json(),
                                target=mechanism_of_action_collection.get_collection_as_json(),
                                modality=modality_collection.get_collection_as_json(),
                                identification_key=identification_key,
                                date_last_changed=date_updated_collection.get_collection_as_json(),
                                date_scraped=date_scraped
                            )
                            treatments.append(master_record.__dict__)
                            processed_treatments.add(treatment_key)

                    except Exception as e:
                        logging.error(f"Error processing indication for {molecule_name}: {e}", exc_info=True)

            except Exception as e:
                logging.error(f"Error processing treatment row: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Merck.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Merck's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Merck script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []