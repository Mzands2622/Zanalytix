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

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_bayer_html():
    """
    Fetches the Bayer pipeline HTML via Zyte.
    """
    try:
        url = "https://www.bayer.com/en/pharma/development-pipeline"
        return url

    except Exception as e:
        logging.error(f"Error fetching Bayer pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_bayer_html(html_content):
    """
    Parses the Bayer pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Bayer pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Bayer script returned no HTML content. Please investigate!"
            )
            return []

        treatments = []
        processed_treatments = set()
        soup = BeautifulSoup(html_content, 'html.parser')

        # Find the relevant table or data area. 
        # Adjust 'tr' to more specific selectors if necessary.
        pipeline_items = soup.find_all('tr')

        for row in pipeline_items:
            cells = row.find_all('td')

            # Adjust the index requirements and data mapping as needed
            if len(cells) >= 4:
                # Extract and clean text for each column
                phase = clean_phase(cells[0].get_text(strip=True))
                area = clean_text(cells[1].get_text(strip=True).replace('\n', ' '))
                program_mode_of_action = clean_text(cells[2].get_text(strip=True).replace('\n', ' '))
                indication = clean_text(cells[3].get_text(strip=True).replace('\n', ' '))

                # Generate unique identification key
                identification_key = generate_identification_key("Bayer", program_mode_of_action, indication)

                # Build a tuple to avoid duplicates
                treatment_key = (area, program_mode_of_action, indication, phase)
                if treatment_key in processed_treatments:
                    continue

                # Multilingual data: area, program_mode_of_action, indication, target, etc.
                area_translator = MultilingualData()
                program_mode_of_action_translator = MultilingualData()
                indication_translator = MultilingualData()
                phase_translator = MultilingualData()

                area_translator.add_translation("en", area)
                program_mode_of_action_translator.add_translation("en", program_mode_of_action)
                indication_translator.add_translation("en", indication)
                phase_translator.add_translation("en", phase)

                # Create the multilingual collections
                area_collection = MultilingualDataCollection()
                program_mode_of_action_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()

                # Add the translator objects to their respective collections
                area_collection.add_data(area_translator)
                program_mode_of_action_collection.add_data(program_mode_of_action_translator)
                indication_collection.add_data(indication_translator)
                phase_collection.add_data(phase_translator)

                # Build the MasterTable record
                master_record = MasterTable(
                    company_name="Bayer",
                    therapeutic_area=area_collection.get_collection_as_json(),
                    target=program_mode_of_action_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Bayer.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Bayer's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Bayer script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []