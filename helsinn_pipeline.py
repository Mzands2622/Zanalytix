from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,
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
async def fetch_helsinn_html():
    """
    Returns the Helsinn pipeline URL.
    """
    try:
        url = "https://www.helsinn.com/technology/life-cycle-development/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Helsinn pipeline URL: {e}")
        return None

# -----------------------
# Map Filled to Stage
# -----------------------
def map_filled_to_stage(val: float) -> str:
    """
    Maps a data-filled numeric value to a textual pipeline stage.
    """
    if val < 1:
        return "Preclinical"
    elif val < 2:
        return "Phase 1"
    elif val < 3:
        return "Phase 2"
    elif val < 4:
        return "Phase 3"
    elif val < 5:
        return "Regulatory"
    else:
        return "Unknown"


# -----------------------
# Process HTML Function
# -----------------------
async def process_helsinn_html(html_content):
    """
    Parses Helsinn's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Helsinn pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Helsinn script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Collect footnotes
        footnotes = {}
        footnote_paras = soup.select('p.body-l.body-s')
        for fp in footnote_paras:
            text = fp.get_text(strip=True)
            match = re.match(r'^(\d+)\.\s+(.*)$', text)
            if match:
                key = match.group(1)
                val = clean_text(match.group(2))
                footnotes[key] = val

        final_data = []

        # 2) Gather pipeline items
        pipeline_items = soup.select('.pipeline__wrap.js-pipeline')
        for item in pipeline_items:
            title_el = item.select_one('h2.pipeline__title')
            if not title_el:
                continue

            raw_title = clean_text(title_el.get_text(strip=True))

            # footnotes in <sup> within the h2
            sup_tags = title_el.select('sup')
            sup_list = [footnotes.get(sup_tag.get_text(strip=True), "") for sup_tag in sup_tags]
            footnote_str = " ".join(filter(None, sup_list))

            # Remove digits (like footnote references) from the displayed title
            clean_title = re.sub(r'\d+', '', raw_title).strip()

            # Check pipeline stage from "data-filled" attribute
            stage_str = "Unknown"
            pipes_wrap = item.select_one('.pipeline__pipes-wrap.js-pipes-filled')
            if pipes_wrap and pipes_wrap.has_attr('data-filled'):
                try:
                    val_float = float(pipes_wrap['data-filled'])
                    stage_str = clean_phase(map_filled_to_stage(val_float))
                except ValueError:
                    pass

            # Additional notes from <div class="rte"> if present
            note_div = item.select_one('.rte > p')
            notes = note_div.get_text(strip=True) if note_div else ""
            if footnote_str:
                # append footnote text
                notes += f"; {footnote_str}" if notes else footnote_str

            indication = "Unknown"
            country = None
            # We check patterns like "... for XXX" or "... in XXX"
            match_for = re.search(r'\bfor\s+(.*)', clean_title, re.IGNORECASE)
            match_in = re.search(r'\bin\s+(.*)', clean_title, re.IGNORECASE)
            drug_name = clean_title

            if match_for:
                indication_part = match_for.group(1).strip()
                drug_name = clean_title[: match_for.start()].strip()
                # Check if it's a country
                if indication_part.lower() in ["china", "u.s.", "us", "usa"]:
                    country = indication_part
                else:
                    indication = indication_part
            elif match_in:
                in_part = match_in.group(1).strip()
                drug_name = clean_title[: match_in.start()].strip()
                if in_part.lower() in ["china", "u.s.", "us", "usa"]:
                    country = in_part
                else:
                    indication = in_part

            record = {
                "drug_name": drug_name,
                "indication": indication,
                "pipeline_stage": stage_str,
                "country": country if country else "Unknown",
                "notes": notes
            }
            final_data.append(record)

        # 3) Convert to MasterTable objects
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in final_data:
            # -- Clean everything before generating the key or translator fields --
            drug_name_cln = clean_text(entry["drug_name"])
            indication_cln = clean_text(entry["indication"])
            pipeline_stage_cln = clean_text(entry["pipeline_stage"])  # or could do clean_phase again if you prefer
            country_cln = clean_text(entry["country"])
            notes_cln = clean_text(entry["notes"])

            # identification key
            identification_key = generate_identification_key(
                "Helsinn",
                drug_name_cln,
                indication_cln,
                country_cln
            )

            # Build multilingual data
            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication_cln)

            country_trans = MultilingualData()
            country_trans.add_translation("en", country_cln)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes_cln)

            name_trans = MultilingualData()
            name_trans.add_translation("en", drug_name_cln)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", pipeline_stage_cln)

            # Collections
            indication_collection = MultilingualDataCollection()
            country_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            indication_collection.add_data(indication_trans)
            country_collection.add_data(country_trans)
            notes_collection.add_data(notes_trans)
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (drug_name_cln, indication_cln, pipeline_stage_cln, country_cln, notes_cln)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Helsinn",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    country=country_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Helsinn.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Helsinn's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Helsinn script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []