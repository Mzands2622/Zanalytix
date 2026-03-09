import re
import logging
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# --- From your original code references ---
from function_app import (
    fetch_with_zyte,  # Not used here since you're directly calling requests
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_csl_html():
    """
    Fetches the CSL pipeline HTML.
    """
    try:
        url = 'https://www.csl.com/research-and-development/product-pipeline'
        return url
    except Exception as e:
        logging.error(f"Error fetching CSL pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_csl_html(html_content):
    """
    Parses the CSL pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        # Since you're directly fetching again, the 'html_content' arg is unused below.
        # If you prefer to pass in 'html_content' from outside, remove the direct requests.get call.
        url = 'https://www.csl.com/research-and-development/product-pipeline'
        response = requests.get(url)
        response.raise_for_status()
        html_content = response.text
        
        if not html_content:
            logging.warning("No HTML content received for CSL pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="CSL script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Color mapping for therapeutic areas
        color_mapping = {
            "#03b3be": "Immunology",
            "#ce2052": "Hematology",
            "#97a81f": "Cardiovascular and Metabolic",
            "#0e56a5": "Nephrology and Transplant",
            "#f06125": "Respiratory",
            "#7030a0": "Vaccines",
            "#00a28a": "CSL Vifor",
            "#cccccc": "Outlicensed Programs",
        }

        # Find all phase sections
        phase_sections = soup.find_all('div', class_='category-phase')

        # Loop through each phase section
        for phase_section in phase_sections:
            # Extract and clean the phase name
            raw_phase = phase_section.select_one('div.phase')
            phase_name = raw_phase.text.strip() if raw_phase else "Unknown Phase"
            phase_name = clean_phase(phase_name)

            # Find all treatments under this phase
            treatment_sections = phase_section.find_all('a', class_='p-item')

            for treatment in treatment_sections:
                try:
                    # Extract text
                    raw_treatment_name = treatment.select_one('p.p-name')
                    raw_description = treatment.select_one('p.p-content')
                    data_color = treatment.get('data-color', 'Unknown')

                    # Convert them to strings or fallback
                    treatment_name = raw_treatment_name.text.strip() if raw_treatment_name else "N/A"
                    description = raw_description.text.strip() if raw_description else "N/A"

                    # Map color to therapeutic area
                    therapeutic_area = color_mapping.get(data_color, "Unknown")

                    # Clean text fields
                    treatment_name = clean_text(treatment_name)
                    therapeutic_area = clean_text(therapeutic_area)
                    description = clean_text(description)

                    # Generate identification key
                    identification_key = generate_identification_key(
                        "CSL",
                        treatment_name,
                        therapeutic_area
                    )
                    date_scraped = datetime.now(timezone.utc)

                    # Prepare multilingual data
                    treatment_name_translator = MultilingualData()
                    therapeutic_area_translator = MultilingualData()
                    description_translator = MultilingualData()
                    phase_translator = MultilingualData()

                    treatment_name_translator.add_translation("en", treatment_name)
                    therapeutic_area_translator.add_translation("en", therapeutic_area)
                    description_translator.add_translation('en', description)
                    phase_translator.add_translation("en", phase_name)

                    treatment_name_collection = MultilingualDataCollection()
                    therapeutic_area_collection = MultilingualDataCollection()
                    description_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()

                    treatment_name_collection.add_data(treatment_name_translator)
                    therapeutic_area_collection.add_data(therapeutic_area_translator)
                    description_collection.add_data(description_translator)
                    phase_collection.add_data(phase_translator)

                    # Create a deduplication key
                    treatment_key = (treatment_name, therapeutic_area, phase_name)

                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="CSL",
                            treatment_name=treatment_name_collection.get_collection_as_json(),
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            notes=description_collection.get_collection_as_json(),
                            identification_key=identification_key,
                            date_scraped=date_scraped
                        )
                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

                except Exception as e:
                    logging.error(f"Error processing treatment: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for CSL.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping CSL's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in CSL script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []