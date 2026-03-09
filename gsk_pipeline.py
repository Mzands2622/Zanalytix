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
async def fetch_gsk_html():
    """
    Fetches the GSK pipeline HTML via Zyte.
    """
    try:
        url = "https://www.gsk.com/en-gb/innovation/pipeline/"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching GSK pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_gsk_html(html_content):
    """
    Parses the GSK pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for GSK pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="GSK script returned no HTML content. Please investigate!"
            )
            return []
            
        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Therapy area color mapping
        therapy_area_mapping = {
            "#244ea2": "Infectious Diseases",
            "#e21860": "HIV",
            "#ffc709": "Respiratory / Immunology",
            "#69b445": "Oncology",
            "#6658a6": "Opportunity Driven"
        }

        # Extract update information
        pipeline_update_info = soup.select_one('h3.pipeline-info__title')
        date_last_changed = pipeline_update_info.text if pipeline_update_info else "Not available"

        initial_name = ""
        rows = soup.select('tr.compounds-table__row')

        for row in rows:
            try:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    # Extract treatment name
                    text_parts = []
                    for p in cells[0].find_all('p', class_='compounds-table__cell-text'):
                        text_parts.append(p.get_text(strip=True))
                    initial_name = ' '.join(text_parts)
                    
                    compound_number_generic_name_brand_name = clean_text(initial_name)

                    # Extract other fields
                    phase = clean_phase(cells[2].text)
                    therapy_area_color = cells[0]['data-therapy-area']
                    therapeutic_area = therapy_area_mapping.get(therapy_area_color.strip(), "Unknown")
                    mode_of_action_vaccine_type = clean_text(cells[3].text)
                    indication = clean_text(cells[1].text)

                    if mode_of_action_vaccine_type == "":
                        break

                    # Generate keys
                    identification_key = generate_identification_key("GSK", compound_number_generic_name_brand_name, therapeutic_area,
                                                                   indication)
                    date_scraped = datetime.now(timezone.utc)
                    treatment_key = (therapeutic_area, compound_number_generic_name_brand_name, phase, indication)

                    # Setup multilingual data
                    therapeutic_area_translator = MultilingualData()
                    indication_translator = MultilingualData()
                    mode_of_action_vaccine_type_translator = MultilingualData()
                    name_translator = MultilingualData()
                    phase_translator = MultilingualData()
                    date_updated_translator = MultilingualData()

                    therapeutic_area_translator.add_translation("en", therapeutic_area)
                    indication_translator.add_translation("en", indication)
                    mode_of_action_vaccine_type_translator.add_translation("en", mode_of_action_vaccine_type)
                    name_translator.add_translation("en", compound_number_generic_name_brand_name)
                    phase_translator.add_translation("en", phase)
                    date_updated_translator.add_translation("en", date_last_changed)

                    therapeutic_area_collection = MultilingualDataCollection()
                    indication_collection = MultilingualDataCollection()
                    mode_of_action_vaccine_type_collection = MultilingualDataCollection()
                    name_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()
                    date_updated_collection = MultilingualDataCollection()

                    therapeutic_area_collection.add_data(therapeutic_area_translator)
                    indication_collection.add_data(indication_translator)
                    mode_of_action_vaccine_type_collection.add_data(mode_of_action_vaccine_type_translator)
                    name_collection.add_data(name_translator)
                    phase_collection.add_data(phase_translator)
                    date_updated_collection.add_data(date_updated_translator)

                    # Create master record if not duplicate
                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="GSK",
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            treatment_name=name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            target=mode_of_action_vaccine_type_collection.get_collection_as_json(),
                            date_scraped=date_scraped,
                            identification_key=identification_key,
                            date_last_changed=date_updated_collection.get_collection_as_json()
                        )
                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(f"Error processing pipeline row: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for GSK.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping GSK's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in GSK script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []