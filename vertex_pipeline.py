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
async def fetch_vertex_html():
    """
    Fetches the Vertex pipeline HTML via Zyte.
    """
    try:
        url = "https://www.vrtx.com/our-science/pipeline/"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Vertex pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_vertex_html(html_content):
    """
    Parses the Vertex pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Vertex Pharmaceuticals pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Vertex script returned no HTML content. Please investigate!"
            )
            return []
            
        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Process each therapeutic area section
        sections = soup.find_all('div', class_='field__item')

        for section in sections:
            try:
                # Extract therapeutic area
                therapeutic_area_tag = section.select_one('span.field--name-name')
                therapeutic_area = clean_text(
                    therapeutic_area_tag.text.strip() if therapeutic_area_tag else "N/A"
                )

                # Process treatments within the therapeutic area
                treatment_items = section.find_all('div', class_='paragraph--type--hww-medicine')

                for treatment in treatment_items:
                    try:
                        # Extract treatment data
                        name_tag = treatment.select_one('button.field--name-field-hww-headline > span')
                        name = clean_text(name_tag.text.strip() if name_tag else "N/A")

                        # Process phase information
                        phase_tag = treatment.select_one('div.field--name-field-hww-phases')
                        phase = "N/A"
                        if phase_tag:
                            classes = phase_tag.get('class', [])
                            for class_name in classes:
                                if class_name.startswith('phase-'):
                                    phase = class_name.replace('phase-', 'Phase ')
                                    # Handle special phase cases
                                    phase_mappings = {
                                        "Phase p": "Research",
                                        "Phase 12": "Phase 1/2",
                                        "Phase 123": "Phase 1/2/3"
                                    }
                                    phase = phase_mappings.get(phase, phase)

                        # Extract description
                        description_tag = treatment.select_one('div.field--name-field-hww-body > p')
                        description = clean_text(
                            description_tag.text.strip() if description_tag else "N/A"
                        )

                        phase = clean_phase(phase)

                        # Generate keys
                        identification_key = generate_identification_key(
                            "Vertex Pharmaceuticals", name, therapeutic_area
                        )
                        date_scraped = datetime.now(timezone.utc)
                        treatment_key = (name, therapeutic_area, phase, description)

                        # Skip if any required field is N/A
                        if "N/A" in treatment_key:
                            continue

                        # Setup multilingual data
                        therapeutic_area_translator = MultilingualData()
                        description_translator = MultilingualData()
                        name_translator = MultilingualData()
                        phase_translator = MultilingualData()

                        therapeutic_area_translator.add_translation('en', therapeutic_area)
                        description_translator.add_translation('en', description)
                        name_translator.add_translation("en", name)
                        phase_translator.add_translation("en", phase)

                        # Add to collections
                        therapeutic_area_collection = MultilingualDataCollection()
                        description_collection = MultilingualDataCollection()
                        name_collection = MultilingualDataCollection()
                        phase_collection = MultilingualDataCollection()

                        therapeutic_area_collection.add_data(therapeutic_area_translator)
                        description_collection.add_data(description_translator)
                        name_collection.add_data(name_translator)
                        phase_collection.add_data(phase_translator)

                        # Create master record if not duplicate
                        if treatment_key not in processed_treatments:
                            master_record = MasterTable(
                                company_name="Vertex Pharmaceuticals",
                                treatment_name=name_collection.get_collection_as_json(),
                                therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                                phase=phase_collection.get_collection_as_json(),
                                notes=description_collection.get_collection_as_json(),
                                identification_key=identification_key,
                                date_scraped=date_scraped
                            )
                            treatments.append(master_record.__dict__)
                            processed_treatments.add(treatment_key)

                    except Exception as e:
                        logging.error(f"Error processing treatment {name if 'name' in locals() else 'unknown'}: {e}", 
                                    exc_info=True)
                        continue

            except Exception as e:
                logging.error(f"Error processing section: {e}", exc_info=True)
                continue

        logging.info(f"Processed {len(treatments)} treatments for Vertex.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Vertex Pharmaceuticals' Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Vertex Pharmaceuticals script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []