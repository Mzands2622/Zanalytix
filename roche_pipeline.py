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
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import logging
import json

async def fetch_roche_html():
    try:
        # Fetch HTML using Zyte API
        url = "https://www.roche.com/solutions/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Roche HTML: {e}")
        return None

async def process_roche_html(html_content):
    try:
        if not html_content:
            logging.warning("No HTML content received for Roche pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Roche script returned no HTML content. Please investigate!"
            )
            return []
            
        treatments = []
        processed_treatments = set()

        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        pipeline_table = soup.find('roche-pipeline-table')

        if not pipeline_table:
            logging.warning("No pipeline table found.")
            return []

        # Extract JSON data from 'content' attribute
        content_json = pipeline_table.get('content')
        if not content_json:
            logging.warning("No content attribute found.")
            return []

        pipeline_data = json.loads(content_json)

        for entry in pipeline_data:
            # Extract data fields
            compound = clean_text(entry.get('name', ''))
            generic_name = clean_text(entry.get('genericName', ''))
            trade_name = clean_text(entry.get('tradeName', ''))
            indication = clean_text(entry.get('indicationShort', ''))
            phase = clean_phase(entry.get('phase', ''))
            filing_date = clean_text(entry.get('filingDate', ''))
            therapeutic_area = clean_text(entry.get('therapeuticArea', ''))
            project_type = clean_text(entry.get('projectType', ''))
            managed_by = clean_text(entry.get('managedBy', ''))
            partner = clean_text(entry.get('partner', ''))
            comment = clean_text(entry.get('comment', ''))
            description = clean_text(entry.get('description', ''))

            # Skip incomplete data
            if not all([therapeutic_area, compound, indication]):
                logging.warning("Skipping entry due to missing key components.")
                continue

            # Generate identification key
            identification_key = generate_identification_key("Roche", compound, indication, trade_name, generic_name)

            # Create multilingual data
            therapeutic_area_translator = MultilingualData()
            indication_translator = MultilingualData()
            generic_name_translator = MultilingualData()
            project_type_translator = MultilingualData()
            managed_by_translator = MultilingualData()
            partner_translator = MultilingualData()
            comment_translator = MultilingualData()
            description_translator = MultilingualData()
            treatment_name_translator = MultilingualData()
            phase_translator = MultilingualData()
            filing_date_translator = MultilingualData()

            therapeutic_area_translator.add_translation("en", therapeutic_area)
            indication_translator.add_translation("en", indication)
            generic_name_translator.add_translation("en", generic_name)
            project_type_translator.add_translation("en", project_type)
            managed_by_translator.add_translation("en", managed_by)
            partner_translator.add_translation("en", partner)
            comment_translator.add_translation("en", comment)
            description_translator.add_translation("en", description)
            treatment_name_translator.add_translation("en", compound)
            phase_translator.add_translation("en", phase)
            filing_date_translator.add_translation("em", filing_date)

            therapeutic_area_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            generic_name_collection = MultilingualDataCollection()
            project_type_collection = MultilingualDataCollection()
            managed_by_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            comment_collection = MultilingualDataCollection()
            description_collection = MultilingualDataCollection()
            treatment_name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            filing_date_collection = MultilingualDataCollection()

            therapeutic_area_collection.add_data(therapeutic_area_translator)
            indication_collection.add_data(indication_translator)
            generic_name_collection.add_data(generic_name_translator)
            project_type_collection.add_data(project_type_translator)
            managed_by_collection.add_data(managed_by_translator)
            partner_collection.add_data(partner_translator)
            comment_collection.add_data(comment_translator)
            description_collection.add_data(description_translator)
            treatment_name_collection.add_data(treatment_name_translator)
            phase_collection.add_data(phase_translator)
            filing_date_collection.add_data(filing_date_translator)

            # Create a unique treatment key
            treatment_key = (therapeutic_area, compound, generic_name, indication, phase)

            # Avoid duplicates
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Roche",
                    therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                    treatment_name=treatment_name_collection.get_collection_as_json(),
                    generic_name=generic_name_collection.get_collection_as_json(),
                    type_of_molecule=project_type_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,
                    filing_date=filing_date_collection.get_collection_as_json(),
                    managed_by=managed_by_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    comment=comment_collection.get_collection_as_json(),
                    notes=description_collection.get_collection_as_json()
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Roche.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Roche's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Roche script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []