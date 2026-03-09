import logging
import re
import aiohttp
import asyncio
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# --- From your original code references ---
from function_app import (
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    fetch_with_zyte,
    send_sms
)

async def fetch_abbvie_html():
    try:
        # Fetch HTML using Zyte API
        url = "https://www.abbvie.com/science/pipeline.html"
        return url

    except Exception as e:
        logging.error(f"Error fetching AbbVie HTML: {e}")
        return None

async def process_abbvie_html(html_content):
    """
    Processes AbbVie pipeline HTML. 
    Ensures that text/phase fields are cleaned before usage 
    (including identification key generation).
    """
    try:
        treatments = []
        processed_treatments = set()

        if not html_content:
            logging.warning("No HTML content received for AbbVie pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="AbbVie script returned no HTML content. Please investigate!"
            )
            return []

        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        pipeline_items = soup.find_all('div', class_='cmp-pipeline')

        # Process each pipeline item
        for item in pipeline_items:
            therapeutic_area = item.get('data-asset-focus-area')
            name = item.get('data-title')
            target = item.get('data-asset-target')
            type_of_molecule = item.get('data-asset-type')

            # -------------------------------------------------
            # 1) SCRAPE DESCRIPTION => "notes_text"
            # -------------------------------------------------
            description_container = item.find('div', class_='description-container')
            notes_text = ""
            if description_container:
                p_tag = description_container.find('p', class_='description')
                if p_tag and p_tag.text.strip():
                    notes_text = p_tag.text.strip()

            # -------------------------------------------------
            # 2) SCRAPE TAGS => also appended to "notes_text"
            # -------------------------------------------------
            tags_container = item.find('div', class_='tags-container')
            if tags_container:
                tag_spans = tags_container.find_all('span', class_='chip')
                tags_list = [span.get_text(strip=True) for span in tag_spans]
                tags_string = "; " + "; ".join(tags_list) if tags_list else ""
                notes_text = (notes_text + tags_string).strip()

            # Clean the notes text
            notes_text_cln = clean_text(notes_text)

            # Create multilingual data for notes
            notes_translator = MultilingualData()
            notes_translator.add_translation("en", notes_text_cln)
            notes_collection = MultilingualDataCollection()
            notes_collection.add_data(notes_translator)

            # Process phases
            phase_elements = item.find_all('div', class_='phase-element')
            for phase_element in phase_elements:
                phases_containers = phase_element.find_all('div', class_='phases-container')
                for container in phases_containers:
                    # --------------------------------------------
                    # EXTRACT INDICATION
                    # --------------------------------------------
                    indication_div = container.find('div', class_='col1')
                    if not indication_div:
                        continue
                    indication = indication_div.get_text(strip=True)

                    # --------------------------------------------
                    # EXTRACT PHASE
                    # --------------------------------------------
                    phase_div = container.find('div', class_='col3')
                    if not phase_div:
                        continue
                    bar_div = phase_div.find('div', class_='bar')
                    if not bar_div:
                        continue
                    phase_class = bar_div.get('class', [])
                    # Use your existing clean_phase to standardize the text
                    phase = clean_phase(phase_class[-1]) if phase_class else None

                    # --------------------------------------------
                    # EXTRACT REGION (COUNTRY)
                    # --------------------------------------------
                    country_text = ""
                    country_div = container.find('div', class_='col2 desktop-element')
                    if country_div:
                        region_label_span = country_div.find('span', class_='region-label')
                        if region_label_span:
                            country_text = region_label_span.get_text(strip=True)

                    # Now clean each relevant text field
                    indication_cln = clean_text(indication)
                    therapeutic_area_cln = clean_text(therapeutic_area)
                    name_cln = clean_text(name)
                    target_cln = clean_text(target)
                    type_of_molecule_cln = clean_text(type_of_molecule)
                    country_cln = clean_text(country_text)

                    # Validate identification key fields
                    if not all([therapeutic_area_cln, name_cln, indication_cln]):
                        logging.warning("Skipping entry due to missing key components.")
                        continue

                    # Generate identification key using 
                    # the *cleaned* name and indication.
                    identification_key = generate_identification_key(
                        "AbbVie",
                        name_cln,
                        indication_cln
                    )

                    # Create multilingual data
                    therapeutic_area_translator = MultilingualData()
                    target_translator = MultilingualData()
                    type_of_molecule_translator = MultilingualData()
                    indication_translator = MultilingualData()
                    country_translator = MultilingualData()
                    treatment_translator = MultilingualData()
                    phase_translator = MultilingualData()

                    therapeutic_area_translator.add_translation("en", therapeutic_area_cln)
                    target_translator.add_translation("en", target_cln)
                    type_of_molecule_translator.add_translation("en", type_of_molecule_cln)
                    indication_translator.add_translation("en", indication_cln)
                    country_translator.add_translation("en", country_cln)
                    treatment_translator.add_translation("en", name_cln)
                    phase_translator.add_translation("en", phase)

                    therapeutic_area_collection = MultilingualDataCollection()
                    target_collection = MultilingualDataCollection()
                    type_of_molecule_collection = MultilingualDataCollection()
                    indication_collection = MultilingualDataCollection()
                    country_collection = MultilingualDataCollection()
                    treatment_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()

                    therapeutic_area_collection.add_data(therapeutic_area_translator)
                    target_collection.add_data(target_translator)
                    type_of_molecule_collection.add_data(type_of_molecule_translator)
                    indication_collection.add_data(indication_translator)
                    country_collection.add_data(country_translator)
                    treatment_collection.add_data(treatment_translator)
                    phase_collection.add_data(phase_translator)

                    # Create a unique key for duplicates check
                    # including the newly cleaned fields
                    treatment_key = (
                        therapeutic_area_cln,
                        name_cln,
                        target_cln,
                        type_of_molecule_cln,
                        indication_cln,
                        phase,
                        country_cln
                    )

                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="AbbVie",
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            treatment_name=treatment_collection.get_collection_as_json(),
                            target=target_collection.get_collection_as_json(),
                            type_of_molecule=type_of_molecule_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            date_scraped=datetime.now(timezone.utc),
                            identification_key=identification_key,
                            notes=notes_collection.get_collection_as_json(),
                            country=country_collection.get_collection_as_json()
                        )

                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

        # Log the number of processed treatments
        logging.info(f"Processed {len(treatments)} treatments for AbbVie.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping AbbVie's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in AbbVie script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
