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


async def fetch_ipsen_html():
    """
    Fetch the raw HTML content from Ipsen's pipeline page using Zyte (via fetch_with_zyte).
    """
    try:
        url = "https://www.ipsen.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Ipsen HTML: {e}")
        return None


def build_phase_map(soup):
    """
    Builds a dynamic map of row classes (gr-row-3, gr-row-5, etc.) to phase names
    by reading the text of each header in .cell.header h5.
    """
    phase_map = {}
    phase_headers = soup.select(".cell.header h5")

    # For each header (Phase – I, Phase – II, etc.), map them to row classes: gr-row-3, gr-row-5, etc.
    for idx, header in enumerate(phase_headers):
        row_class = f"gr-row-{3 + idx * 2}"  # 3, 5, 7, 9, ...
        phase_map[row_class] = header.get_text(strip=True)
    return phase_map


async def process_ipsen_html(html_content):
    """
    Process the HTML content into structured data using the new sibling-walk approach.
    Returns a list of MasterTable.__dict__ objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Ipsen pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Ipsen script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Scrape the "date last updated" text from the desired element (if present)
        date_last_updated_text_element = soup.select_one(
            "div.column-1.col-xl-12.col-md-12.col-sm-12 .accordian-info .accordian-summary.visible"
        )
        date_last_updated_text = (
            date_last_updated_text_element.get_text(strip=True)
            if date_last_updated_text_element
            else None
        )
        date_last_updated_text = clean_text(date_last_updated_text)  # Clean up the text

        logging.info(f"Date Last Updated Text: {date_last_updated_text}")

        # 2) Build the dynamic phase map
        phase_map = build_phase_map(soup)

        treatments = []
        processed_treatments = set()

        # 3) Find all therapy sections
        therapy_sections = soup.find_all("div", class_="therapy-title")

        for therapy_section in therapy_sections:
            # The therapy area (e.g., "Oncology", "Rare Diseases", etc.)
            therapy_name_el = therapy_section.find("h4")
            if not therapy_name_el:
                continue

            disease_area = clean_text(therapy_name_el.get_text(strip=True))

            # Walk siblings until the next therapy title
            rows_for_this_therapy = []
            sibling = therapy_section.next_sibling

            while sibling:
                # Stop if we reach another therapy title
                if (
                    sibling.name == "div"
                    and "therapy-title" in sibling.get("class", [])
                ):
                    break

                # Collect if it's a pipeline row: class starts with "gr-row-"
                if (
                    sibling.name == "div"
                    and any(cls.startswith("gr-row-") for cls in sibling.get("class", []))
                ):
                    rows_for_this_therapy.append(sibling)

                sibling = sibling.next_sibling

            # Now parse only these rows for the current therapy
            for row in rows_for_this_therapy:
                row_classes = row.get("class", [])
                # Identify phase using the dynamic phase_map
                row_phase = next((phase_map.get(cls) for cls in row_classes if cls in phase_map), None)
                if not row_phase:
                    continue

                # Find each cell in this row
                cells = row.find_all("div", class_="cell-content")
                for cell in cells:
                    compound_el = cell.find("h5")
                    indication_el = cell.find("p")

                    compound_text = clean_text(compound_el.get_text(strip=True)) if compound_el else ""
                    indication_text = clean_text(indication_el.get_text(strip=True)) if indication_el else ""

                    phase = clean_phase(row_phase)

                    # Generate identification key
                    identification_key = generate_identification_key(
                        "Ipsen", compound_text, disease_area, indication_text
                    )

                    # Build multilingual data for each field
                    disease_area_translator = MultilingualData()
                    disease_area_translator.add_translation("en", disease_area)

                    treatment_name_translator = MultilingualData()
                    treatment_name_translator.add_translation("en", compound_text)

                    indication_translator = MultilingualData()
                    indication_translator.add_translation("en", indication_text)

                    phase_translator = MultilingualData()
                    phase_translator.add_translation("en", phase)

                    date_updated_translator = MultilingualData()
                    date_updated_translator.add_translation("en", date_last_updated_text)

                    # Build multilingual collections
                    disease_area_collection = MultilingualDataCollection()
                    disease_area_collection.add_data(disease_area_translator)

                    treatment_name_collection = MultilingualDataCollection()
                    treatment_name_collection.add_data(treatment_name_translator)

                    indication_collection = MultilingualDataCollection()
                    indication_collection.add_data(indication_translator)

                    phase_collection = MultilingualDataCollection()
                    phase_collection.add_data(phase_translator)

                    date_updated_collection = MultilingualDataCollection()
                    date_updated_collection.add_data(date_updated_translator)

                    # Create a unique key to avoid duplicates
                    treatment_key = (disease_area, compound_text, indication_text, phase)
                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="Ipsen Global",
                            therapeutic_area=disease_area_collection.get_collection_as_json(),
                            treatment_name=treatment_name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            date_scraped=datetime.now(timezone.utc),
                            identification_key=identification_key,
                            # We store the date last updated (scraped from site) here
                            date_last_changed=date_updated_collection.get_collection_as_json()
                        )
                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Ipsen.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Ipsen's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Ipsen script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
