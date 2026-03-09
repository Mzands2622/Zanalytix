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

async def fetch_spyre_html():
    """
    Fetches the Spyre pipeline URL via Zyte.
    """
    try:
        url = "https://spyre.com/pipeline/"        
        return url
    except Exception as e:
        logging.error(f"Error fetching Spyre HTML: {e}")
        return None

async def process_spyre_html(html_content):
    """
    Parses the Spyre pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Spyre pipeline.")
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        treatments = []
        processed_treatments = set()

        # Find all pipeline table rows
        table_rows = soup.select(".block-pipeline .row.table-row")
        
        if not table_rows:
            logging.warning("No pipeline table rows found.")
            send_sms(
                phone_number="9144334333",
                message="Spyre script found no pipeline table rows. Please investigate!"
            )
            return []

        for table_row in table_rows:
            cols = table_row.select(".col.table-col")
            if len(cols) < 2:
                continue

            # Extract comment from first column
            comment_el = cols[0].select_one("h3.title")
            raw_comment = comment_el.get_text(" ", strip=True) if comment_el else ""

            # Process pipeline items from second column
            right_rows = cols[1].select(".row.right-row")

            for item_row in right_rows:
                subcols = item_row.select(".col")
                if len(subcols) < 3:
                    continue

                # Extract raw data
                raw_target = subcols[0].get_text(strip=True)
                raw_treatment_name = subcols[1].get_text(strip=True)
                
                phase_el = subcols[2].select_one(".bar-title")
                raw_phase = phase_el.get_text(strip=True) if phase_el else "N/A"
                
                notes_el = subcols[2].select_one(".accordion-content")
                raw_notes = notes_el.get_text(strip=True) if notes_el else ""

                # Clean text fields
                comment = clean_text(raw_comment)
                target = clean_text(raw_target)
                treatment_name = clean_text(raw_treatment_name)
                phase = clean_phase(raw_phase)
                notes = clean_text(raw_notes)

                # Generate identification key using full treatment name
                identification_key = generate_identification_key(
                    "Spyre Therapeutics",
                    treatment_name,
                    target
                )

                # Create multilingual data objects
                comment_translator = MultilingualData()
                target_translator = MultilingualData()
                treatment_name_translator = MultilingualData()
                phase_translator = MultilingualData()
                notes_translator = MultilingualData()

                comment_translator.add_translation("en", comment)
                target_translator.add_translation("en", target)
                treatment_name_translator.add_translation("en", treatment_name)
                phase_translator.add_translation("en", phase)
                notes_translator.add_translation("en", notes)

                # Create collections
                comment_collection = MultilingualDataCollection()
                target_collection = MultilingualDataCollection()
                treatment_name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()
                notes_collection = MultilingualDataCollection()

                comment_collection.add_data(comment_translator)
                target_collection.add_data(target_translator)
                treatment_name_collection.add_data(treatment_name_translator)
                phase_collection.add_data(phase_translator)
                notes_collection.add_data(notes_translator)

                # Build unique key for deduplication
                treatment_key = (comment, target, treatment_name, phase)

                # Create MasterTable record if not duplicate
                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Spyre Therapeutics",
                        comment=comment_collection.get_collection_as_json(),
                        target=target_collection.get_collection_as_json(),
                        treatment_name=treatment_name_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        notes=notes_collection.get_collection_as_json(),
                        date_scraped=datetime.now(timezone.utc),
                        identification_key=identification_key
                    )

                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Spyre.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Spyre Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Spyre script: {e}. Please investigate!"
        )
        return []