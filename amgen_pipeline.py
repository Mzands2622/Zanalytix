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
# Helper Function
# -----------------------
def _extract_text_or_none(element, selector):
    """
    Safely extract .text from a sub-element found via `selector`, 
    or return None if not found.
    """
    found = element.select_one(selector)
    return found.get_text(strip=True) if found else None


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_amgen_html():
    """
    Fetches the Amgen pipeline HTML via Zyte.
    """
    try:
        # URL to scrape
        url = "https://www.amgenpipeline.com/"
        return url

    except Exception as e:
        logging.error(f"Error fetching Amgen HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_amgen_html(html_content):
    """
    Parses the Amgen pipeline HTML and returns a list of serialized
    MasterTable objects.

    This function:
    - Finds each top-level 'row collapsibleContent' (molecule section).
    - Extracts the molecule name from the left column.
    - Iterates over '.wrapper.row' blocks in the right column for 
      therapeutic area, indication, modality, phase, and description.
    - Uses your cleaning and translation logic.
    - Avoids duplicates by tracking a set of unique keys.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Amgen pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Amgen script returned no HTML content. Please investigate!"
            )
            return []

        treatments = []
        processed_treatments = set()
        soup = BeautifulSoup(html_content, 'html.parser')
        treatment_count = 0

        # 1) All top-level blocks for each molecule
        molecule_sections = soup.find_all('div', class_='row collapsibleContent')

        for section in molecule_sections:
            # ------------------------
            # Extract Molecule Name
            # ------------------------
            molecule_name = clean_text(
                _extract_text_or_none(section, '.col-sm-3.border-right .textContent')
                or "Molecule name not available"
            )

            # ------------------------
            # The right column that has multiple "wrapper row"
            # ------------------------
            right_col = section.select_one('.col-sm-9')
            if not right_col:
                continue

            # Each "wrapper row" inside this molecule's block
            wrapper_rows = right_col.find_all('div', class_='wrapper row')

            for wrapper in wrapper_rows:
                # --- THERAPEUTIC AREA ---
                therapeutic_area = clean_text(
                    _extract_text_or_none(wrapper, '.first-column .tarea-text')
                    or "Therapeutic area not available"
                )

                # --- Phase ---
                phase = clean_phase(
                    _extract_text_or_none(wrapper, '.fourth-column .badge')
                    or "Phase not available"
                )

                # --- Indication and Modality ---
                second_col = clean_text(
                    _extract_text_or_none(wrapper, '.second-column .card-block a')
                    or "Indication not available"
                )
                third_col = clean_text(
                    _extract_text_or_none(wrapper, '.third-column .card-block a')
                    or "Modality not available"
                )

                if second_col == "Investigational Indication":
                    indication = third_col
                    modality = "Modality not available"
                else:
                    indication = second_col
                    modality = third_col

                # --- Description ---
                # The description is often in the next sibling with .collapseData
                description = "Description not available"
                possible_next = wrapper.find_next_sibling('div', class_='collapseData')
                if possible_next:
                    description = clean_text(
                        _extract_text_or_none(possible_next, '.innterContentText')
                        or "Description not available"
                    )

                # Generate identification key
                identification_key = generate_identification_key(
                    "Amgen", molecule_name, therapeutic_area, indication
                )
                date_scraped = datetime.now(timezone.utc)

                # Multilingual data setup
                therapeutic_area_translator = MultilingualData()
                indication_translator = MultilingualData()
                modality_translator = MultilingualData()
                description_translator = MultilingualData()
                molecule_name_translator = MultilingualData()
                phase_translator = MultilingualData()

                therapeutic_area_translator.add_translation("en", therapeutic_area)
                indication_translator.add_translation("en", indication)
                modality_translator.add_translation("en", modality)
                description_translator.add_translation("en", description)
                molecule_name_translator.add_translation("en", molecule_name)
                phase_translator.add_translation("en", phase)

                therapeutic_area_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                modality_collection = MultilingualDataCollection()
                description_collection = MultilingualDataCollection()
                molecule_name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()

                therapeutic_area_collection.add_data(therapeutic_area_translator)
                indication_collection.add_data(indication_translator)
                modality_collection.add_data(modality_translator)
                description_collection.add_data(description_translator)
                molecule_name_collection.add_data(molecule_name_translator)
                phase_collection.add_data(phase_translator)

                # Create a unique key to avoid duplicates
                treatment_key = (molecule_name, description, phase, indication, therapeutic_area, str(treatment_count))
                treatment_count += 1

                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Amgen",
                        phase=phase_collection.get_collection_as_json(),
                        therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                        treatment_name=molecule_name_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        target=modality_collection.get_collection_as_json(),
                        # You can choose what "type_of_molecule" or "notes" represent
                        notes=description_collection.get_collection_as_json(),
                        identification_key=identification_key,
                        date_scraped=date_scraped
                    )

                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Amgen.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Amgen's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Amgen script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []