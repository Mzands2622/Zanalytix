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

async def fetch_biogen_html():
    """
    Returns the Biogen pipeline URL.
    """
    try:
        # If you actually need to fetch the HTML here, you can do:
        # html_content = await fetch_with_zyte(url)
        # return html_content
        # For now, we're just returning the URL for the Zyte fetch in your main pipeline process.
        url = "https://www.biogen.com/science-and-innovation/pipeline.html"
        return url
    except Exception as e:
        logging.error(f"Error fetching Biogen HTML: {e}")
        return None

async def process_biogen_html(html_content):
    """
    Parses Biogen's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Biogen pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Biogen script returned no HTML content. Please investigate!"
            )
            return []
            
        treatments = []
        processed_treatments = set()

        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_rows = soup.select("div.json-table-list-item")
        if not pipeline_rows:
            logging.warning("No pipeline rows found on Biogen page.")
            return []

        for row in pipeline_rows:
            data_div = row.select_one("div.json-table-item-data")
            if not data_div:
                continue

            # 1) Extract fields (and clean them immediately)
            disease_area = clean_text(
                data_div.select_one(".disease-areas").text.strip()
            ) if data_div.select_one(".disease-areas") else ""

            name = clean_text(
                data_div.select_one(".name").text.strip()
            ) if data_div.select_one(".name") else ""

            modality = clean_text(
                data_div.select_one(".desc").text.strip()
            ) if data_div.select_one(".desc") else ""

            phase = clean_phase(
                data_div.select_one(".phase").text.strip()
            ) if data_div.select_one(".phase") else ""

            # 2) Additional description (notes)
            desc_div = row.select_one("div.json-table-item-description p.description")
            description = clean_text(
                desc_div.text.strip()
            ) if desc_div else ""

            # 3) Skip incomplete data if critical fields are missing
            if not all([disease_area, name, modality]):
                logging.warning("Skipping entry due to missing key components.")
                continue

            # 4) Generate identification key *after* cleaning
            identification_key = generate_identification_key("Biogen", name, disease_area, modality)

            # 5) Create MultilingualData objects
            disease_area_translator = MultilingualData()
            modality_translator = MultilingualData()
            description_translator = MultilingualData()
            name_translator = MultilingualData()
            phase_translator = MultilingualData()

            disease_area_translator.add_translation("en", disease_area)
            modality_translator.add_translation("en", modality)
            description_translator.add_translation("en", description)
            name_translator.add_translation("en", name)
            phase_translator.add_translation("en", phase)

            # 6) Convert them into MultilingualDataCollections
            disease_area_collection = MultilingualDataCollection()
            modality_collection = MultilingualDataCollection()
            description_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            disease_area_collection.add_data(disease_area_translator)
            modality_collection.add_data(modality_translator)
            description_collection.add_data(description_translator)
            name_collection.add_data(name_translator)
            phase_collection.add_data(phase_translator)

            # 7) Create a unique treatment key to avoid duplicates
            treatment_key = (disease_area, name, modality, phase)
            if treatment_key not in processed_treatments:
                processed_treatments.add(treatment_key)
                
                master_record = MasterTable(
                    company_name="Biogen",
                    therapeutic_area=disease_area_collection.get_collection_as_json(),
                    treatment_name=name_collection.get_collection_as_json(),
                    type_of_molecule=modality_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    notes=description_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)

        logging.info(f"Processed {len(treatments)} treatments for Biogen.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Biogen's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Biogen script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []