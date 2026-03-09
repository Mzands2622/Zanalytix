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
async def fetch_johnson_johnson_html():
    """
    Fetches the Johnson & Johnson pipeline HTML via Zyte.
    """
    try:
        url = "https://www.investor.jnj.com/pipeline/development-pipeline/default.aspx"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Johnson & Johnson pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_johnson_johnson_html(html_content):
    """
    Parses the Johnson & Johnson pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Johnson&Johnson pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Johnson&Johnson script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Process each therapeutic area section
        areas = soup.select("section.pipeline-area")
        for area in areas:
            try:
                area_name = clean_text(area.select_one("h2.pipeline-area_title").text.strip())

                # Process cards within each area
                cards = area.select("li.pipeline-area_card")
                for card in cards:
                    try:
                        # Extract basic information
                        treatment_name = clean_text(card.select_one("h3.pipeline-area_card-title").text.strip())
                        indication = clean_text(card.select_one("p.pipeline-area_card-description").text.strip())
                        phase_initial = clean_text(card.select_one("p.pipeline-area_card-phase").text.strip())
                        phase = clean_phase(phase_initial)

                        # Generate keys
                        identification_key = generate_identification_key("Johnson&Johnson", treatment_name, indication)
                        date_scraped = datetime.now(timezone.utc)
                        treatment_key = (area_name, treatment_name, phase, indication)

                        # Setup multilingual data
                        therapeutic_area_translator = MultilingualData()
                        indication_translator = MultilingualData()
                        name_translator = MultilingualData()
                        phase_translator = MultilingualData()

                        therapeutic_area_translator.add_translation("en", area_name)
                        indication_translator.add_translation("en", indication)
                        name_translator.add_translation("en", treatment_name)
                        phase_translator.add_translation("en", phase)

                        therapeutic_area_collection = MultilingualDataCollection()
                        indication_collection = MultilingualDataCollection()
                        name_collection = MultilingualDataCollection()
                        phase_collection = MultilingualDataCollection()

                        therapeutic_area_collection.add_data(therapeutic_area_translator)
                        indication_collection.add_data(indication_translator)
                        name_collection.add_data(name_translator)
                        phase_collection.add_data(phase_translator)

                        # Create master record if not duplicate
                        if treatment_key not in processed_treatments:
                            master_record = MasterTable(
                                company_name="Johnson&Johnson",
                                therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                                treatment_name=name_collection.get_collection_as_json(),
                                indication=indication_collection.get_collection_as_json(),
                                phase=phase_collection.get_collection_as_json(),
                                date_scraped=date_scraped,
                                identification_key=identification_key
                            )
                            treatments.append(master_record.__dict__)
                            processed_treatments.add(treatment_key)

                    except Exception as e:
                        logging.error(f"Error processing card in area {area_name}: {e}", exc_info=True)

            except Exception as e:
                logging.error(f"Error processing therapeutic area: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Johnson & Johnson.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Johnson&Johnson's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Johnson&Johnson script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []