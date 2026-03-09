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
async def fetch_gilead_html():
    """
    Fetches the Gilead Sciences pipeline HTML via Zyte.
    """
    try:
        url = "https://www.gilead.com/science/pipeline"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Gilead Sciences pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_gilead_html(html_content):
    """
    Parses the Gilead Sciences pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Gilead pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Gilead script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Extract update information
        update_info = soup.find("p", class_="gl-white")
        date_last_changed = update_info.text.strip() if update_info else None

        # Extract each pipeline item
        for pipeline_item in soup.select("li.list-pipeline-wrapper"):
            try:
                # Extract basic information
                therapeutic_area = clean_text(pipeline_item.get("data-category", "").strip())
                tag = clean_text(pipeline_item.get("data-tag", "").strip())
                order = clean_text(pipeline_item.get("data-order", "").strip())

                # Extract detailed fields
                treatment_name = clean_text(
                    pipeline_item.select_one(".field-headbrandname").text.strip()
                    if pipeline_item.select_one(".field-headbrandname") else "N/A"
                )
                indication = clean_text(
                    pipeline_item.select_one(".field-potentialindication").text.strip()
                    if pipeline_item.select_one(".field-potentialindication") else "N/A"
                )
                phase_info = clean_text(
                    pipeline_item.select_one(".phase-name").text.strip()
                    if pipeline_item.select_one(".phase-name") else "N/A"
                )
                notes = clean_text(
                    pipeline_item.select_one(".field-notesdetail").get_text(separator=" ").strip()
                    if pipeline_item.select_one(".field-notesdetail") else "No additional notes"
                )

                # Map phase to numeric value if possible, otherwise store whatever the pipeline says
                phase_cleaned = clean_phase(phase_info)

                # Generate identification key and treatment key
                date_scraped = datetime.now(timezone.utc)
                identification_key = generate_identification_key(
                    "Gilead Sciences", 
                    treatment_name, 
                    therapeutic_area, 
                    indication
                )
                treatment_key = (therapeutic_area, treatment_name, phase_cleaned, indication, notes)

                # Setup multilingual data
                therapeutic_area_translator = MultilingualData()
                indication_translator = MultilingualData()
                notes_translator = MultilingualData()
                name_translator = MultilingualData()
                phase_translator = MultilingualData()
                date_updated_translator = MultilingualData()
                disease_area_translator = MultilingualData()

                therapeutic_area_translator.add_translation("en", therapeutic_area)
                indication_translator.add_translation("en", indication)
                notes_translator.add_translation("en", notes)
                name_translator.add_translation("en", treatment_name)
                phase_translator.add_translation("en", phase_cleaned)  # store numeric as string if you prefer
                date_updated_translator.add_translation("en", date_last_changed if date_last_changed else "Unknown")
                disease_area_translator.add_translation("en", tag)

                therapeutic_area_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                notes_collection = MultilingualDataCollection()
                name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()
                date_updated_collection = MultilingualDataCollection()
                disease_area_collection = MultilingualDataCollection()

                therapeutic_area_collection.add_data(therapeutic_area_translator)
                indication_collection.add_data(indication_translator)
                notes_collection.add_data(notes_translator)
                name_collection.add_data(name_translator)
                phase_collection.add_data(phase_translator)
                date_updated_collection.add_data(date_updated_translator)
                disease_area_collection.add_data(disease_area_translator)

                # Create master record if not duplicate
                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Gilead",
                        therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                        treatment_name=name_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        notes=notes_collection.get_collection_as_json(),
                        date_scraped=date_scraped,
                        identification_key=identification_key,
                        date_last_changed=date_updated_collection.get_collection_as_json(),
                        disease_area=disease_area_collection.get_collection_as_json()
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(f"Error processing pipeline item: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Gilead Sciences.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Gilead's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Gilead script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []