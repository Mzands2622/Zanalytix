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
async def fetch_recordati_html():
    """
    Returns the Pharvaris pipeline URL.
    """
    try:
        url = "https://www.recordatirarediseases.com/rd/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Pharvaris pipeline URL: {e}")
        return None


# -----------------------
# Map Class to Phase
# -----------------------
def map_w_to_phase(w_class: str) -> str:
    """
    Maps a class like 'w61' to a textual phase based on intervals of 20.
    """
    try:
        num = int(w_class[1:])
    except ValueError:
        return "Unknown"

    if num <= 20:
        return "Discovery"
    elif num <= 40:
        return "Preclinical development"
    elif num <= 60:
        return "Proof of concept trials"
    elif num <= 80:
        return "Late-stage/registration trials"
    else:
        return "Registration"


# -----------------------
# Split Drug and Indication
# -----------------------
def split_drug_and_indication(full_string: str):
    """
    Splits a full string into drug_name and indication based on keywords like 'for', 'in', or 'due to'.
    """
    lower_str = full_string.lower()
    if " due to " in lower_str:
        splitted = re.split(r'\sdue to\s', full_string, flags=re.IGNORECASE, maxsplit=1)
        drug = splitted[0].strip()
        indic = splitted[1].strip()
    elif " for " in lower_str:
        splitted = re.split(r'\sfor\s', full_string, flags=re.IGNORECASE, maxsplit=1)
        drug = splitted[0].strip()
        indic = splitted[1].strip()
    elif " in " in lower_str:
        splitted = re.split(r'\sin\s', full_string, flags=re.IGNORECASE, maxsplit=1)
        drug = splitted[0].strip()
        indic = splitted[1].strip()
    else:
        drug = full_string.strip()
        indic = ""

    return drug, indic


# -----------------------
# Process HTML Function
# -----------------------
async def process_recordati_html(html_content):
    """
    Parses Recordati's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Recordati pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Recordati script returned no HTML content. Please investigate!"
            )
            return []
        soup = BeautifulSoup(html_content, "html.parser")

        pipeline_data = []
        pipeline_blocks = soup.select('div.module_pipeline')

        for block in pipeline_blocks:
            section_header = block.select_one('h2.color-primary')
            section_name = clean_text(section_header.get_text(strip=True)) if section_header else ""

            pipeline_wrappers = block.select('.pipeline-wrapper')
            for wrapper in pipeline_wrappers:
                pipeline_name = wrapper.select_one('.pipeline-name')
                raw_name = pipeline_name.get_text(strip=True) if pipeline_name else ""
                drug_name_clean, indication_clean = split_drug_and_indication(raw_name)

                overlay = wrapper.select_one('.pipeline .pipeline-overlay')
                pipeline_stage = ""
                if overlay:
                    overlay_classes = overlay.get('class', [])
                    for cls_ in overlay_classes:
                        if cls_.startswith('w'):
                            pipeline_stage = clean_phase(map_w_to_phase(cls_))
                            break

                partner_span = wrapper.select_one('.pipeline-partner')
                partner = clean_text(partner_span.get_text(strip=True)) if partner_span else ""

                rights_span = wrapper.select_one('.pipeline-rights')
                rights = clean_text(rights_span.get_text(strip=True)) if rights_span else ""

                pipeline_data.append({
                    "therapeutic_area": section_name,
                    "drug_name": drug_name_clean,
                    "indication": indication_clean,
                    "pipeline_stage": pipeline_stage,
                    "partner": partner,
                    "rights": rights
                })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            therapeutic_area = clean_text(entry["therapeutic_area"])
            drug_name = clean_text(entry["drug_name"])
            indication = clean_text(entry["indication"])
            pipeline_stage = clean_phase(entry["pipeline_stage"])
            partner = clean_text(entry["partner"])
            rights = clean_text(entry["rights"])

            identification_key = generate_identification_key("Recordati", drug_name, therapeutic_area, indication)

            # Multilingual Data
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            stage_trans = MultilingualData()
            stage_trans.add_translation("en", pipeline_stage)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", partner)

            rights_trans = MultilingualData()
            rights_trans.add_translation("en", rights)

            name_trans = MultilingualData()
            name_trans.add_translation("en", drug_name)

            # Collections
            area_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            stage_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            rights_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            indication_collection.add_data(indication_trans)
            stage_collection.add_data(stage_trans)
            partner_collection.add_data(partner_trans)
            rights_collection.add_data(rights_trans)
            name_collection.add_data(name_trans)

            treatment_key = (therapeutic_area, drug_name, indication, pipeline_stage, partner, rights)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Recordati",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=stage_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    notes=rights_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Recordati.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Recordati's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Recordati script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []