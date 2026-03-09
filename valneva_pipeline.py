# valneva_pipeline.py

import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Assuming you have these imports from your shared "function_app":
from function_app import (
    clean_phase,               # or adapt your map_progress_to_phase logic below
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    fetch_with_zyte,
    send_sms
)

async def fetch_valneva_html():
    """
    Fetches the Valneva pipeline page via Zyte.
    """
    try:
        url = "https://valneva.com/research-development/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Valneva HTML: {e}")
        return None

def map_progress_to_phase(progress_value):
    """
    Convert a numeric 'progress' (0-100) into a textual phase label.
    The example logic below interprets:
      - p >= 80 => Market Registration
      - p >= 60 => Phase 3
      - p >= 40 => Phase 2
      - p >= 20 => Phase 1
      - p >  0  => Preclinical
      - p == 0  => Unknown
    Adjust as needed based on actual site data or your preference.
    """
    p = int(progress_value)
    if p >= 80:
        return "Market Registration"
    elif p >= 60:
        return "Phase 3"
    elif p >= 40:
        return "Phase 2"
    elif p >= 0:
        return "Phase 1"
    else:
        return "Unknown"

async def process_valneva_html(html_content):
    """
    Parses the Valneva pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Valneva pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Valneva script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_items = soup.select("article.pipelineItem")

        if not pipeline_items:
            logging.warning("No pipeline items found in Valneva's HTML.")
            send_sms(
                phone_number="9144334333",
                message="Valneva script found no pipeline items. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for item in pipeline_items:
            # 1) Extract raw text
            header = item.select_one("header h2")
            full_name = header.get_text(strip=True) if header else ""

            # Split on "–" to separate Indication from Treatment Name
            parts = full_name.split("–")
            if len(parts) >= 2:
                raw_indication = parts[0].strip()
                raw_treatment_name = parts[1].strip()
            else:
                # Fallback if there's no dash or unexpected format
                raw_indication = full_name
                raw_treatment_name = ""

            # Extract progress value => convert to phase
            # NOTE: Removed ".animated" so we just look for <div class="bar" data-progress="X">
            bar = item.select_one("div.progressBar div.bar")
            progress_val = bar.get("data-progress") if bar else "0"
            raw_phase = map_progress_to_phase(progress_val)

            # comment
            content = item.select_one("div.content")
            desc_paragraph = content.select_one("p") if content else None
            raw_comment = desc_paragraph.get_text(strip=True) if desc_paragraph else ""

            # notes
            more_link = content.select_one("a.blockLink.filled") if content else None
            raw_notes = more_link.get("href") if more_link else ""

            # 2) Clean text fields
            indication = clean_text(raw_indication)
            treatment_name = clean_text(raw_treatment_name)
            phase = clean_phase(raw_phase)
            comment = clean_text(raw_comment)
            notes = clean_text(raw_notes)

            # 3) Validate required fields (adjust as needed)
            if not all([indication, treatment_name, phase]):
                logging.warning("Skipping entry due to missing key components.")
                continue

            # 4) Generate identification key
            identification_key = generate_identification_key(
                "Valneva",
                treatment_name,
                indication,
            )

            # 5) Build multilingual data
            indication_translator = MultilingualData()
            treatment_name_translator = MultilingualData()
            phase_translator = MultilingualData()
            comment_translator = MultilingualData()
            notes_translator = MultilingualData()

            indication_translator.add_translation("en", indication)
            treatment_name_translator.add_translation("en", treatment_name)
            phase_translator.add_translation("en", phase)
            comment_translator.add_translation("en", comment)
            notes_translator.add_translation("en", notes)

            indication_collection = MultilingualDataCollection()
            treatment_name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            comment_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()

            indication_collection.add_data(indication_translator)
            treatment_name_collection.add_data(treatment_name_translator)
            phase_collection.add_data(phase_translator)
            comment_collection.add_data(comment_translator)
            notes_collection.add_data(notes_translator)

            # 6) Create a unique key for deduping
            entry_key = (indication, treatment_name, phase, comment, notes)
            if entry_key not in processed_entries:
                # 7) Construct MasterTable record
                master_record = MasterTable(
                    company_name="Valneva",
                    treatment_name=treatment_name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    comment=comment_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key
                )

                results.append(master_record.__dict__)
                processed_entries.add(entry_key)

        logging.info(f"Processed {len(results)} pipeline entries for Valneva.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Valneva's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Valneva's script: {e}. Please investigate!"
        )
        return []
