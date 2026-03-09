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

async def fetch_ferring_html():
    """
    Fetches the Ferring pipeline URL via Zyte.
    """
    try:
        url = "https://www.ferring.com/science-innovation/research-and-development/product-pipeline/"
        return url
        
        if not html_content:
            logging.warning("No HTML content received for Ferring pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Ferring script returned no HTML content. Please investigate!"
            )
            return None
            
        return html_content
    except Exception as e:
        logging.error(f"Error fetching Ferring HTML: {e}")
        return None

async def process_ferring_html(html_content):
    """
    Parses the Ferring pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Ferring pipeline.")
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Find all accordion sections
        accordion_sections = soup.find_all("div", class_="spb_accordion_section")
        
        if not accordion_sections:
            logging.warning("No accordion sections found.")
            send_sms(
                phone_number="9144334333",
                message="Ferring script found no accordion sections. Please investigate!"
            )
            return []

        for section in accordion_sections:
            heading_tag = section.find("h4")
            if not heading_tag:
                continue

            raw_therapeutic_area = heading_tag.get_text(strip=True)

            tables = section.find_all("table", class_="sf-table")
            if not tables:
                continue

            for table in tables:
                rows = table.find_all("tr")
                data_rows = rows[1:]  # Skip header row

                for row in data_rows:
                    cells = row.find_all('td')
                    if len(cells) < 2:
                        continue

                    # Extract raw data
                    raw_comment = cells[0].get_text(strip=True)
                    raw_indication = cells[1].get_text(strip=True)
                    
                    # Determine phase
                    phase_found = None
                    for i, cell in enumerate(cells[2:], start=2):
                        if cell.find('b') and '✓' in cell.get_text():
                            phase_found = f"Phase {i - 1}"
                            break

                    # Clean text fields
                    therapeutic_area = clean_text(raw_therapeutic_area)
                    comment = clean_text(raw_comment)  # Keep full comment for data
                    indication = clean_text(raw_indication)
                    phase = clean_phase(phase_found) if phase_found else "N/A"

                    # Validate required fields
                    if not all([therapeutic_area, comment, indication]):
                        logging.warning("Skipping entry due to missing key components.")
                        continue

                    # Create truncated comment for key
                    truncated_comment = ' '.join(comment.split()[:5])  # First 5 words for key

                    # Generate identification key using truncated comment
                    identification_key = generate_identification_key(
                        "Ferring",
                        truncated_comment,
                        indication
                    )

                    # Create multilingual data objects
                    therapeutic_area_translator = MultilingualData()
                    comment_translator = MultilingualData()
                    treatment_name_translator = MultilingualData()  # New translator for truncated comment
                    indication_translator = MultilingualData()
                    phase_translator = MultilingualData()

                    therapeutic_area_translator.add_translation("en", therapeutic_area)
                    comment_translator.add_translation("en", comment)
                    treatment_name_translator.add_translation("en", truncated_comment)  # Add truncated version
                    indication_translator.add_translation("en", indication)
                    phase_translator.add_translation("en", phase)

                    # Create collections
                    therapeutic_area_collection = MultilingualDataCollection()
                    comment_collection = MultilingualDataCollection()
                    treatment_name_collection = MultilingualDataCollection()  # New collection
                    indication_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()

                    therapeutic_area_collection.add_data(therapeutic_area_translator)
                    comment_collection.add_data(comment_translator)
                    treatment_name_collection.add_data(treatment_name_translator)  # Add to collection
                    indication_collection.add_data(indication_translator)
                    phase_collection.add_data(phase_translator)

                    # Build unique key for deduplication
                    treatment_key = (therapeutic_area, comment, indication, phase)

                    # Create MasterTable record if not duplicate
                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="Ferring Pharmaceuticals",
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            treatment_name=treatment_name_collection.get_collection_as_json(),  # Truncated comment as treatment_name
                            comment=comment_collection.get_collection_as_json(),  # Full comment stored separately
                            indication=indication_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            date_scraped=datetime.now(timezone.utc),
                            identification_key=identification_key
                        )

                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Ferring.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Ferring Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Ferring script: {e}. Please investigate!"
        )
        return []