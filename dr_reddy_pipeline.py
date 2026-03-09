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

async def fetch_dr_reddy_html():
    """
    Fetches the Dr. Reddy pipeline URL (if you wanted,
    you could fetch the HTML content directly using Zyte here).
    """
    try:
        url = 'https://www.drreddysbiologics.com/products-pipeline'
        return url
    except Exception as e:
        logging.error(f"Error fetching pipeline HTML: {e}")
        return None

async def process_dr_reddy_html(html_content):
    """
    Parses the Dr. Reddy Biologics pipeline page,
    logs scraped entries vs processed entries, and returns
    a list of MasterTable dictionaries.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Dr. Reddys Laboratories pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Dr. Reddys laboratories script returned no HTML content. Please investigate!"
            )
            return []

        # This list will store EVERY row you scrape,
        # even if it’s a duplicate or incomplete.
        scraped_list = []

        # Final list of treatments (deduplicated).
        treatments = []
        processed_treatments = set()

        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        timeline_items = soup.find_all('div', class_='timeline-item')

        if not timeline_items:
            logging.warning("No timeline-item elements found.")
            return []

        for item in timeline_items:
            # Extract year(s)
            year_tag = item.find('div', class_='year')
            # Clean the text right away
            year_raw = year_tag.text.strip() if year_tag else 'Unknown'
            year = clean_text(year_raw)

            # Extract therapeutic areas and treatments
            sections = item.find_all('p')
            for section in sections:
                # We look for the '–' delimiter
                if '–' in section.text:
                    parts = section.text.split('–')
                    # Clean these strings before usage
                    therapeutic_area_raw = parts[0].strip()
                    treatments_text_raw = parts[1].strip()

                    therapeutic_area = clean_text(therapeutic_area_raw)
                    treatments_text = clean_text(treatments_text_raw)

                    # Keep a record in scraped_list
                    scraped_list.append({
                        'year': year,
                        'therapeutic_area': therapeutic_area,
                        'treatments_text': treatments_text
                    })

                    # Deduplication key
                    treatment_key = (year, therapeutic_area, treatments_text)

                    # Generate identification key
                    # (Now using the cleaned strings)
                    identification_key = generate_identification_key(
                        "dr_reddy",
                        treatments_text,    # already cleaned
                        therapeutic_area,   # already cleaned
                        year                # already cleaned
                    )

                    # Set up multilingual data
                    therapeutic_area_translator = MultilingualData()
                    year_translator = MultilingualData()
                    treatment_translator = MultilingualData()

                    therapeutic_area_translator.add_translation("en", therapeutic_area)
                    year_translator.add_translation("en", year)
                    treatment_translator.add_translation("en", treatments_text)

                    therapeutic_area_collection = MultilingualDataCollection()
                    year_collection = MultilingualDataCollection()
                    treatment_collection = MultilingualDataCollection()

                    therapeutic_area_collection.add_data(therapeutic_area_translator)
                    year_collection.add_data(year_translator)
                    treatment_collection.add_data(treatment_translator)

                    # Create the MasterTable record (always),
                    # but only add to 'treatments' once per unique key.
                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="Dr. Reddys Laboratories",
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            # Store the actual pipeline "treatments_text" in the JSON field
                            treatment_name=treatment_collection.get_collection_as_json(),
                            date_scraped=datetime.now(timezone.utc),
                            identification_key=identification_key,
                            # Using 'filing_date' for 'year'
                            filing_date=year_collection.get_collection_as_json()
                        )

                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)
                    else:
                        logging.info(f"Skipping duplicate: {treatment_key}")

        # Log everything: how many were scraped vs. how many finally processed
        logging.info(f"SCRAPED total items: {len(scraped_list)}")
        logging.info(f"PROCESSED unique items: {len(treatments)}")

        logging.info("SCRAPED ITEMS:")
        for item in scraped_list:
            logging.info(f"  {item}")

        logging.info("PROCESSED TREATMENTS:")
        for t in treatments:
            logging.info(f"  {t}")

        logging.info(f"Processed {len(treatments)} treatments for Dr.Reddy.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Dr. Reddys Laboratories Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Dr. Reddys Laboratories script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
