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
import requests


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_novo_nordisk_html():
    """
    Fetches the Novo Nordisk pipeline URL.
    (Note that this just returns the URL, you can adjust to actually fetch the HTML via Zyte if desired.)
    """
    try:
        url = "https://www.novonordisk.com/science-and-technology/r-d-pipeline.html"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Novo Nordisk pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_novo_nordisk_html(html_content):
    """
    Parses the Novo Nordisk pipeline HTML (already fetched, e.g., via Zyte) 
    and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Novo Nordisk pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Novo Nordisk script returned no HTML content. Please investigate!"
            )
            return []

        # Parse the HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Find the pipeline container
        pipeline_container = soup.find('div', class_="phasesgrid")
        if not pipeline_container:
            logging.error("Could not find pipeline container.")
            return []

        # Process each phase
        phase_items = pipeline_container.find_all('div', class_="phase-item")
        for phase_item in phase_items:
            try:
                # Extract the actual phase name from <h4 class="phase-header">
                phase_header = phase_item.find("h4", class_="phase-header")
                phase_name_raw = phase_header.get_text(strip=True) if phase_header else "Unknown Phase"
                # Clean the phase name
                phase_name = clean_phase(phase_name_raw)

                # Inside each phase-item, there's a div class="area"
                area_div = phase_item.find('div', class_="area")
                if not area_div:
                    continue

                # Each .rndarea-wrapper is a single treatment
                rnd_wrappers = area_div.find_all("div", class_="rndarea-wrapper")
                for wrapper in rnd_wrappers:
                    # Inside .rndarea-wrapper, there's .area-item with <h4> (treatment name) and <p> (indication)
                    area_item = wrapper.find("div", class_="area-item")
                    if not area_item:
                        continue

                    h4_tag = area_item.find("h4", class_="h4")
                    raw_name = h4_tag.get_text(strip=True) if h4_tag else "No name found"
                    treatment_name = clean_text(raw_name)

                    p_tag = area_item.find("p", class_="paragraph-s")
                    raw_indication = p_tag.get_text(strip=True) if p_tag else "No indication found"
                    indication = clean_text(raw_indication)

                    # Generate a unique key
                    identification_key = generate_identification_key("Novo Nordisk", treatment_name, indication)

                    # Build a Python-friendly tuple key to avoid duplicates
                    date_scraped = datetime.now(timezone.utc)
                    treatment_key = (treatment_name, indication, phase_name)

                    # Setup multilingual data
                    indication_translator = MultilingualData()
                    indication_translator.add_translation("en", indication)
                    indication_collection = MultilingualDataCollection()
                    indication_collection.add_data(indication_translator)

                    name_translator = MultilingualData()
                    name_translator.add_translation("en", treatment_name)
                    name_collection = MultilingualDataCollection()
                    name_collection.add_data(name_translator)

                    phase_translator = MultilingualData()
                    phase_translator.add_translation("en", phase_name)
                    phase_collection = MultilingualDataCollection()
                    phase_collection.add_data(phase_translator)

                    # Create MasterTable record if not a duplicate
                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="Novo Nordisk",
                            treatment_name=name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            identification_key=identification_key,
                            date_scraped=date_scraped
                        )
                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(f"Error processing phase: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Novo Nordisk.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Novo Nordisk's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Novo Nordisk script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
