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

async def fetch_eli_lilly_html():
    """
    Fetches the Eli Lilly pipeline URL via Zyte.
    """
    try:
        # URL to scrape
        url = 'https://www.lilly.com/innovation/clinical-development-pipeline#'
        return url
    except Exception as e:
        logging.error(f"Error fetching Lilly HTML: {e}")
        return None

async def process_eli_lilly_html(html_content):
    """
    Parses the Eli Lilly pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Eli Lilly and Company pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Eli Lilly and Company script returned no HTML content. Please investigate!"
            )
            return []


        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Find all pipeline cards
        cards = soup.find_all('div', class_='pipeline-card')
        if not cards:
            logging.warning("No pipeline-card elements found.")
            send_sms(
                phone_number="9144334333", 
                message="Eli Lilly and Company script returned no Pipeline Cards Found! Please investigate!"
            )
            return []

        for card in cards:
            # ----------------------------------------------------------------
            # 1) Extract raw attributes
            # ----------------------------------------------------------------
            raw_title      = card.get('title', 'N/A')
            raw_phase      = card.get('phase', 'N/A')
            body_html      = card.get('body_html', '')
            indication_div = card.find('div', class_='indication')
            raw_indication = indication_div.get_text(strip=True) if indication_div else 'N/A'
            class_list     = card.get('class', [])

            # ----------------------------------------------------------------
            # 2) Clean text fields and unify the data
            # ----------------------------------------------------------------
            name        = clean_text(raw_title)
            phase       = clean_phase(raw_phase)
            description = clean_text(BeautifulSoup(body_html, 'html.parser').get_text(strip=True))
            indication  = clean_text(raw_indication)

            # Override phase if it’s '4'
            if phase == "4":
                phase = "Regulatory Review"

            # Derive therapeutic area from the extra class in class_list
            therapeutic_area = 'N/A'
            for cls in class_list:
                if cls not in ['pipeline-card', 'mb-3', 'collapsed']:
                    # E.g., 'oncology-pipeline' => 'Oncology Pipeline'
                    # Then .title() => 'Oncology Pipeline'
                    # Or do a different transform if you prefer
                    therapeutic_area = clean_text(cls.replace('-', ' ').title())

            # ----------------------------------------------------------------
            # 3) Validate required fields
            # ----------------------------------------------------------------
            if not all([therapeutic_area, name, indication]):
                logging.warning("Skipping entry due to missing key components.")
                continue

            # ----------------------------------------------------------------
            # 4) Generate the identification key with *cleaned* values
            # ----------------------------------------------------------------
            identification_key = generate_identification_key(
                "Eli Lilly",
                name,
                indication
            )

            # ----------------------------------------------------------------
            # 5) Build multilingual data objects (with cleaned text)
            # ----------------------------------------------------------------
            therapeutic_area_translator = MultilingualData()
            indication_translator       = MultilingualData()
            description_translator      = MultilingualData()
            name_translator             = MultilingualData()
            phase_translator            = MultilingualData()

            therapeutic_area_translator.add_translation("en", therapeutic_area)
            indication_translator.add_translation("en", indication)
            description_translator.add_translation("en", description)
            name_translator.add_translation("en", name)
            phase_translator.add_translation("en", phase)

            therapeutic_area_collection = MultilingualDataCollection()
            indication_collection       = MultilingualDataCollection()
            description_collection      = MultilingualDataCollection()
            name_collection             = MultilingualDataCollection()
            phase_collection            = MultilingualDataCollection()

            therapeutic_area_collection.add_data(therapeutic_area_translator)
            indication_collection.add_data(indication_translator)
            description_collection.add_data(description_translator)
            name_collection.add_data(name_translator)
            phase_collection.add_data(phase_translator)

            # ----------------------------------------------------------------
            # 6) Build a unique key for deduplication
            # ----------------------------------------------------------------
            treatment_key = (therapeutic_area, name, indication, phase)

            # ----------------------------------------------------------------
            # 7) Create MasterTable record if it’s not a duplicate
            # ----------------------------------------------------------------
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Eli Lilly and Company",
                    therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,
                    notes=description_collection.get_collection_as_json()
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Lilly.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Eli Lilly and Company's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Eli Lilly and Companys script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []