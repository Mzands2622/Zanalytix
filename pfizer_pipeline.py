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
import requests
import logging
import re

def extract_notes(text):
    """
    Extract all text within parentheses and return both the cleaned text and notes
    """
    notes = []
    cleaned_text = text.strip()

    # Find all text within parentheses
    matches = re.findall(r'\(([^()]+)\)', cleaned_text)

    # Add each parenthetical text to notes
    for match in matches:
        notes.append(match.strip())
        cleaned_text = cleaned_text.replace(f"({match})", "").strip()

    # Clean up any trailing parentheses
    cleaned_text = re.sub(r'\)+$', '', cleaned_text).strip()

    return cleaned_text, notes

def get_non_capitalized_notes(notes):
    """Get notes that are not fully capitalized (ignoring punctuation)"""
    non_cap_notes = []
    for note in notes:
        # Remove punctuation and spaces for checking capitalization
        cleaned_note = re.sub(r'[,\s\-\.]', '', note)
        # Check if the note contains any lowercase letters
        if not cleaned_note.isupper() or not any(c.isalpha() for c in cleaned_note):
            non_cap_notes.append(note)
    return non_cap_notes

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_pfizer_html():
    """
    Fetches the Pfizer pipeline HTML via Zyte.
    """
    try:
        url = "https://www.pfizer.com/v1/pipeline/filter"
        return url

    except Exception as e:
        logging.error(f"Error fetching Pfizer pipeline HTML: {e}")
        return None

async def process_pfizer_html(html_content):
    """
    Parses the Pfizer pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        # Get the last updated date from the main pipeline page
        main_url = "https://www.pfizer.com/science/drug-product-pipeline"
        main_response = requests.get(main_url)
        if main_response.status_code == 200:
            main_soup = BeautifulSoup(main_response.text, 'html.parser')
            date_element = main_soup.find('p', class_='pipeline-txt-date')
            date_last_changed_str = clean_text(date_element.text) if date_element else "No date found"
            logging.info(f"Found last changed date: {date_last_changed_str}")
        else:
            logging.error(f"Failed to fetch main page with status code: {main_response.status_code}")
            date_last_changed_str = "No date found"

        # Setup API parameters
        base_url = "https://www.pfizer.com/v1/pipeline/filter"
        params = {
            'ugcf_project_discontinued[]': 'current',
            'search': '',
            'order': 'ugcf_phase_of_development',
            'limit': '10',
            'pager': 'true',
            'style': 'detailed'
        }

        # Get total page count
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch data with status code: {response.status_code}")
            return None

        data = response.json()
        total_pages = data['data']['page_count']
        treatments = []
        processed_treatments = set()

        # Process all pages
        for page in range(0, total_pages + 1):
            try:
                params['page'] = page
                response = requests.get(base_url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    products = data['data']['products']

                    for product_id, product_info in products.items():
                        try:
                            # Extract product data
                            area_of_focus = clean_text(product_info.get('field_ugcf_therapeutic_area', ''))
                            compound_name = clean_text(product_info.get('field_ugcf_compound_name', ''))
                            raw_indication = clean_text(product_info.get('field_ugcf_indication', ''))
                            compound_type = clean_text(product_info.get('field_ugcf_compound_type', ''))
                            phase = clean_phase(product_info.get('field_ugcf_phase_of_development', ''))
                            mechanism_of_action = clean_text(product_info.get('field_ugcf_mechanism_of_action', ''))
                            submission_type = clean_text(product_info.get('field_ugcf_submission_type', ''))

                            # Extract notes and clean indication
                            cleaned_indication, notes = extract_notes(raw_indication)
                            non_cap_notes = get_non_capitalized_notes(notes)

                            # Generate keys
                            identification_key = generate_identification_key("Pfizer", compound_name, cleaned_indication, str(non_cap_notes))
                            date_scraped = datetime.now(timezone.utc)
                            
                            # Include non-capitalized notes in the treatment key
                            treatment_key = (
                                area_of_focus, compound_name, mechanism_of_action, 
                                compound_type, cleaned_indication, phase, submission_type,
                                str(notes)
                            )

                            # Setup multilingual data
                            area_of_focus_translator = MultilingualData()
                            indication_translator = MultilingualData()
                            compound_type_translator = MultilingualData()
                            mechanism_of_action_translator = MultilingualData()
                            submission_type_translator = MultilingualData()
                            name_translator = MultilingualData()
                            phase_translator = MultilingualData()
                            date_updated_translator = MultilingualData()
                            notes_translator = MultilingualData()  # New translator for notes

                            # Add translations
                            area_of_focus_translator.add_translation("en", area_of_focus)
                            indication_translator.add_translation("en", cleaned_indication)
                            compound_type_translator.add_translation("en", compound_type)
                            mechanism_of_action_translator.add_translation("en", mechanism_of_action)
                            submission_type_translator.add_translation("en", submission_type)
                            name_translator.add_translation("en", compound_name)
                            phase_translator.add_translation("en", phase)
                            date_updated_translator.add_translation("en", date_last_changed_str)
                            notes_text = "; ".join(notes) if notes else ""  # Join all notes with semicolon
                            notes_translator.add_translation("en", notes_text)

                            # Create collections
                            area_of_focus_collection = MultilingualDataCollection()
                            indication_collection = MultilingualDataCollection()
                            compound_type_collection = MultilingualDataCollection()
                            mechanism_of_action_collection = MultilingualDataCollection()
                            submission_type_collection = MultilingualDataCollection()
                            name_collection = MultilingualDataCollection()
                            phase_collection = MultilingualDataCollection()
                            date_updated_collection = MultilingualDataCollection()
                            notes_collection = MultilingualDataCollection()  # New collection for notes

                            # Add data to collections
                            area_of_focus_collection.add_data(area_of_focus_translator)
                            indication_collection.add_data(indication_translator)
                            compound_type_collection.add_data(compound_type_translator)
                            mechanism_of_action_collection.add_data(mechanism_of_action_translator)
                            submission_type_collection.add_data(submission_type_translator)
                            name_collection.add_data(name_translator)
                            phase_collection.add_data(phase_translator)
                            date_updated_collection.add_data(date_updated_translator)
                            notes_collection.add_data(notes_translator)  # Add notes to collection

                            # Create master record if not duplicate
                            if treatment_key not in processed_treatments:
                                master_record = MasterTable(
                                    company_name="Pfizer",
                                    therapeutic_area=area_of_focus_collection.get_collection_as_json(),
                                    treatment_name=name_collection.get_collection_as_json(),
                                    indication=indication_collection.get_collection_as_json(),
                                    type_of_molecule=compound_type_collection.get_collection_as_json(),
                                    phase=phase_collection.get_collection_as_json(),
                                    target=mechanism_of_action_collection.get_collection_as_json(),
                                    submission_type=submission_type_collection.get_collection_as_json(),
                                    identification_key=identification_key,
                                    date_last_changed=date_updated_collection.get_collection_as_json(),
                                    notes=notes_collection.get_collection_as_json(),  # Add notes to final dict
                                    date_scraped=date_scraped
                                )
                                treatments.append(master_record.__dict__)
                                processed_treatments.add(treatment_key)

                        except Exception as e:
                            logging.error(f"Error processing product {product_id}: {e}", exc_info=True)

                else:
                    logging.error(f"Failed to fetch data for page {page} with status code {response.status_code}")

            except Exception as e:
                logging.error(f"Error processing page {page}: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Pfizer.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Pfizer's Pipeline: {e}")
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Pfizer script: {e}. Please investigate!"
        )
        return []