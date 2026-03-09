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

logging.basicConfig(level=logging.INFO)

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_abcellera_html():
    """
    Returns the AbCellera pipeline URL.
    """
    try:
        url = "https://abcellera.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching AbCellera pipeline URL: {e}")
        return None

# -----------------------
# Process HTML Function
# -----------------------
async def process_abcellera_html(html_content):
    """
    Parses AbCellera's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for AbCellera pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="AbCellera script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        raw_results = []

        # 1) Extract relevant "program_blocks"
        program_blocks = soup.select("section.content-text, section[id^='content-text-block'], div.content-text")
        for block in program_blocks:
            h2_el = block.select_one("h2 > p")
            if h2_el:
                # Clean the drug name as soon as we get it
                raw_drug_name = clean_text(h2_el.get_text(strip=True))
                if not raw_drug_name.startswith("ABCL"):
                    continue

                body_div = block.select_one(".body") or block
                description_paras = body_div.select("p")
                # We'll do a local clean on each paragraph
                cleaned_paras = [clean_text(p.get_text(strip=True)) for p in description_paras]
                notes = "\n".join(cleaned_paras).strip()

                # A very rough guess for indication
                indication = "Unknown"
                if "metabolic and endocrine" in notes.lower():
                    indication = "Metabolic and endocrine conditions"
                elif "atopic dermatitis" in notes.lower():
                    indication = "Atopic dermatitis"

                pipeline_stage = "Preclinical (IND-enabling)"

                raw_results.append({
                    "drug_name": raw_drug_name,
                    "indication": indication,  # We'll do a second pass cleaning below
                    "pipeline_stage": pipeline_stage,  # We'll do a second pass cleaning below
                    "notes": notes,  # Already cleaned
                })

        # ----------------------------
        # 2) Convert each entry => MasterTable
        # ----------------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in raw_results:
            # Ensure everything is cleaned again if needed
            drug_name = clean_text(entry["drug_name"])
            indication = clean_text(entry["indication"])
            pipeline_stage = clean_phase(entry["pipeline_stage"])
            notes_text = entry["notes"]  # Already cleaned above

            # Build ID key from cleaned text
            identification_key = generate_identification_key("AbCellera", drug_name, indication)

            # Prepare multilingual data
            drug_name_trans = MultilingualData()
            indication_trans = MultilingualData()
            pipeline_stage_trans = MultilingualData()
            notes_trans = MultilingualData()

            drug_name_trans.add_translation("en", drug_name)
            indication_trans.add_translation("en", indication)
            pipeline_stage_trans.add_translation("en", pipeline_stage)
            notes_trans.add_translation("en", notes_text)

            drug_name_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            pipeline_stage_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()

            drug_name_collection.add_data(drug_name_trans)
            indication_collection.add_data(indication_trans)
            pipeline_stage_collection.add_data(pipeline_stage_trans)
            notes_collection.add_data(notes_trans)

            # Use a tuple to detect duplicates if we want
            treatment_key = (drug_name, indication, pipeline_stage)
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="AbCellera",
                    treatment_name=drug_name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=pipeline_stage_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for AbCellera.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping AbCellera's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Abcellera script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
