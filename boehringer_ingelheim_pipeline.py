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
async def fetch_boehringer_ingelheim_html():
    """
    Fetches the Boehringer Ingelheim pipeline HTML via Zyte.
    """
    try:
        url = "https://www.boehringer-ingelheim.com/science-innovation/human-health-innovation/clinical-pipeline"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Boehringer Ingelheim pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_boehringer_ingelheim_html(html_content):
    """
    Parses the Boehringer Ingelheim pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Boehringer Ingelheim pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Boehringer Ingelheim script returned no HTML content. Please investigate!"
            )
            return []
            
        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()
        treatment_count = 0

        # Extract last changed date
        date_last_changed = None
        date_element = soup.select_one(".gds-pipeline-hero__intro p")
        if date_element:
            date_last_changed = date_element.text.strip()

        # Parse pipeline sections by phases
        for section in soup.select(".gds-pipeline-accordion"):
            # Extract phase name and clean it
            phase_element = section.select_one("h2.gds-pipeline-accordion__heading button")
            raw_phase = phase_element.text.strip()[:7] if phase_element else "Unknown"
            phase = clean_phase(raw_phase)

            # Parse treatments in this phase
            for card in section.select(".gds-pipeline-project-card"):
                try:
                    # Extract details (raw strings first)
                    raw_therapeutic_area = card.select_one(".gds-pipeline-project-card__heading")
                    raw_indication = card.select_one(".gds-pipeline-project-card__sub-heading")
                    raw_notes = card.select_one(".gds-pipeline-project-card__bottom > p")
                    raw_treatment_name = card.select_one(".gds-pipeline-project-card__substance-name i")

                    # Clean each text field
                    therapeutic_area = clean_text(raw_therapeutic_area.text.strip()) if raw_therapeutic_area else None
                    indication = clean_text(raw_indication.text.strip()) if raw_indication else None
                    notes = clean_text(raw_notes.text.strip()) if raw_notes else None
                    treatment_name = clean_text(raw_treatment_name.text.strip()) if raw_treatment_name else None

                    # Prepare multilingual data
                    therapeutic_area_translator = MultilingualData()
                    indication_translator = MultilingualData()
                    treatment_translator = MultilingualData()
                    target_translator = MultilingualData()  # using 'notes' as 'target' in this script
                    phase_translator = MultilingualData()
                    date_updated_translator = MultilingualData()

                    therapeutic_area_translator.add_translation("en", therapeutic_area)
                    indication_translator.add_translation("en", indication)
                    treatment_translator.add_translation("en", treatment_name)
                    target_translator.add_translation("en", notes)
                    phase_translator.add_translation("en", phase)
                    date_updated_translator.add_translation("en", date_last_changed)

                    therapeutic_area_collection = MultilingualDataCollection()
                    indication_collection = MultilingualDataCollection()
                    treatment_collection = MultilingualDataCollection()
                    target_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()
                    date_updated_collection = MultilingualDataCollection()

                    therapeutic_area_collection.add_data(therapeutic_area_translator)
                    indication_collection.add_data(indication_translator)
                    treatment_collection.add_data(treatment_translator)
                    target_collection.add_data(target_translator)
                    phase_collection.add_data(phase_translator)
                    date_updated_collection.add_data(date_updated_translator)

                    # Generate identification key
                    # (using the already-cleaned text fields)
                    identification_key = generate_identification_key(
                        "Boehringer Ingelheim",
                        treatment_name,
                        therapeutic_area,
                        indication,
                        notes
                    )
                    date_scraped = datetime.now(timezone.utc)

                    # Create a tuple to avoid duplicates
                    treatment_key = (
                        treatment_name, 
                        indication, 
                        phase, 
                        notes, 
                        therapeutic_area, 
                        str(treatment_count)
                    )
                    treatment_count += 1

                    logging.info(f"Creating record with key: {treatment_key}")

                    # Avoid duplicates
                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="Boehringer Ingelheim",
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            treatment_name=treatment_collection.get_collection_as_json(),
                            target=target_collection.get_collection_as_json(),  # Storing 'notes' under 'target'
                            indication=indication_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            date_scraped=date_scraped,
                            identification_key=identification_key,
                            date_last_changed=date_updated_collection.get_collection_as_json()
                        )

                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

                except Exception as e:
                    logging.error(f"Error processing treatment card: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Boehringer Ingelheim.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Boehringer Ingelheims's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Boehringer Ingelheim's script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []