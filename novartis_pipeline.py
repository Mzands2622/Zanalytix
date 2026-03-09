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
import re


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_novartis_html():
    """
    Returns the base URL for Novartis pipeline.
    """
    try:
        url = 'https://www.novartis.com/research-development/novartis-pipeline?search_api_fulltext=&page=0'
        return url
    except Exception as e:
        logging.error(f"Error fetching Novartis pipeline HTML: {e}")
        return None


# -----------------------
# Fetch All Pages Function
# -----------------------
async def fetch_all_pages_novartis(html_content):
    """
    Handles pagination and combines HTML for all pages.
    """
    try:
        # Base URL setup
        base_url = 'https://www.novartis.com/research-development/novartis-pipeline?search_api_fulltext=&page='
        current_page = '1'  # Start from page 1 for additional content
        complete_html = html_content  # Start with initial HTML passed in

        # Pagination loop
        while True:
            # Construct URL for the next page
            page_url = base_url + current_page
            logging.info(f"Fetching page: {page_url}")

            # Fetch the next page's HTML
            new_html_content = await fetch_with_zyte(page_url)
            if not new_html_content:
                logging.error(f"Failed to fetch HTML content from page {current_page}.")
                break  # Exit loop if fetch fails

            # Add new HTML to complete content
            complete_html += new_html_content

            # Check if there's a next page
            soup = BeautifulSoup(new_html_content, 'html.parser')
            next_page_link = soup.select_one('.pager__item--next a')

            # Update current page or break loop
            if next_page_link and 'href' in next_page_link.attrs:
                current_page = next_page_link['href'].split('=')[-1]
                if current_page not in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]:  # Stop at page 10
                    break
            else:
                break  # No more pages

        # Return all combined HTML
        logging.info("Successfully fetched HTML content for all pages.")
        return complete_html

    except Exception as e:
        logging.error(f"Error during pagination: {e}")
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Novartis script: {e}. Please investigate!"
        )
        return []


# -----------------------
# Process HTML Function
# -----------------------
async def process_novartis_html(html_content):
    """
    Parses the HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.error("No HTML content to process for Novartis pipeline.")
            return []

        # Fetch all paginated HTML
        complete_html = await fetch_all_pages_novartis(html_content)
        if not complete_html:
            logging.error("Failed to fetch all paginated HTML content.")
            return []

        treatments = []
        processed_treatments = set()

        # Parse all treatments
        all_treatments = parse_treatments_novartis(complete_html)

        for treatment in all_treatments:
            try:
                # Extract treatment details
                project = clean_text(treatment.get("Project", "Unknown"))
                brand_name = clean_text(treatment.get("Product", "Unknown"))
                indication = clean_text(treatment.get("Indication", "Unknown"))
                therapeutic_area = clean_text(treatment.get("Therapeutic_Area", "Unknown"))
                development_phase = clean_phase(treatment.get("Development_Phase", "Unknown"))
                filing_date = clean_text(treatment.get("Filing_Date", "Unknown"))
                mechanism_of_action = clean_text(treatment.get("Mechanism_of_Action", "Unknown"))
                notes = clean_text(treatment.get("Notes", "Unknown"))


                # Generate keys
                identification_key = generate_identification_key("Novartis", project, indication)
                date_scraped = datetime.now(timezone.utc)
                treatment_key = (
                    project, therapeutic_area, indication, 
                    development_phase, mechanism_of_action
                )

                # Setup multilingual data
                therapeutic_area_translator = MultilingualData()
                indication_translator = MultilingualData()
                mechanism_of_action_translator = MultilingualData()
                treatment_name_translator = MultilingualData()
                phase_translator = MultilingualData()
                brand_name_translator = MultilingualData()
                filing_date_translator = MultilingualData()
                notes_translator = MultilingualData()


                therapeutic_area_translator.add_translation("en", therapeutic_area)
                indication_translator.add_translation("en", indication)
                mechanism_of_action_translator.add_translation("en", mechanism_of_action)
                treatment_name_translator.add_translation("en", project)
                phase_translator.add_translation("en", development_phase)
                brand_name_translator.add_translation("en", brand_name)
                filing_date_translator.add_translation("en", filing_date)
                notes_translator.add_translation("en", notes)

                # Add to collections
                therapeutic_area_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                mechanism_of_action_collection = MultilingualDataCollection()
                treatment_name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()
                brand_name_collection = MultilingualDataCollection()
                filing_date_collection = MultilingualDataCollection()
                notes_collection = MultilingualDataCollection()

                therapeutic_area_collection.add_data(therapeutic_area_translator)
                indication_collection.add_data(indication_translator)
                mechanism_of_action_collection.add_data(mechanism_of_action_translator)
                treatment_name_collection.add_data(treatment_name_translator)
                phase_collection.add_data(phase_translator)
                brand_name_collection.add_data(brand_name_translator)
                filing_date_collection.add_data(filing_date_translator)
                notes_collection.add_data(notes_translator)

                # Create master record if not duplicate
                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Novartis",
                        treatment_name=treatment_name_collection.get_collection_as_json(),
                        therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        target=mechanism_of_action_collection.get_collection_as_json(),
                        identification_key=identification_key,
                        date_scraped=date_scraped,
                        brand_name=brand_name_collection.get_collection_as_json(),
                        filing_date=filing_date_collection.get_collection_as_json(),
                        notes=notes_collection.get_collection_as_json()
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(f"Error processing treatment {project if 'project' in locals() else 'unknown'}: {e}")
                continue

        logging.info(f"Processed {len(treatments)} treatments for Novartis.")
        return treatments

    except Exception as e:
        logging.error(f"Error during processing: {e}")
        return []

def parse_treatments_novartis(html):
    soup = BeautifulSoup(html, 'html.parser')
    treatments = []
    entries = soup.select(".pipeline-main-wrapper")
    for entry in entries:
        name = entry.select_one(".compound-name").text.strip()
        generic_name = entry.select_one(".generic-name").text.strip()
        indication = entry.select_one(".indication-name").text.strip()

        main_indication_div = entry.select_one(".main-indication")
        main_indication_text = main_indication_div.get_text(strip=True) if main_indication_div else ""

        second_main = entry.select(".main-second span")

        # Initialize defaults
        therapeutic_area = "Null"
        phase = "Null"
        approval_year = "Null"
        mechanism_action = "Null"

        # Depending on number and content of spans, assign correctly
        if len(second_main) >= 3:
            therapeutic_area = second_main[0].text.strip()
            phase = clean_phase(second_main[1].text.strip())

            # Use regular expression to detect if it contains a year or range
            year_or_range = second_main[2].text.strip()
            if re.match(r"\d{4}", year_or_range) or "≥" in year_or_range:
                approval_year = year_or_range
                if len(second_main) > 3:
                    mechanism_action = second_main[3].text.strip()
            else:
                mechanism_action = second_main[2].text.strip()

        if len(second_main) <= 2:
            therapeutic_area = second_main[0].text.strip()
            phase = second_main[1].text.strip()

        treatments.append({
            "Company_Name": "Novartis",
            "Project": name,
            "Product": generic_name,
            "Indication": indication,
            "Therapeutic_Area": therapeutic_area,
            "Development_Phase": phase,
            "Filing_Date": approval_year,
            "Mechanism_of_Action": mechanism_action,
            "Notes": main_indication_text
        })

    return treatments