from function_app import (
    fetch_with_zyte,
    clean_phase,         # If you'd like to map phases similarly (optional)
    clean_text,          # If you'd like to clean text similarly (optional)
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

# ---------------------------------------
# PHASE PARSING HELPER (Optional)
# ---------------------------------------
def parse_phase_from_class(class_list):
    """
    Convert the pipeline row class to a textual phase.
    Adjust as needed if more granular mapping is desired.
    """
    if 'clinical' in class_list:
        return "Clinical"
    elif 'discoverypreclinical' in class_list or 'discovery' in class_list:
        return "Discovery/Preclinical"
    else:
        return "Unknown"


# ---------------------------------------
# FETCH HTML FUNCTION
# ---------------------------------------
async def fetch_sarepta_html():
    """
    Returns the Sarepta pipeline URL (similar to fetch_sanofi_html).
    """
    try:
        url = "https://www.sarepta.com/products-pipeline/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Sarepta pipeline URL: {e}", exc_info=True)
        return None


# ---------------------------------------
# PROCESS HTML FUNCTION
# ---------------------------------------
async def process_sarepta_html(html_content):
    """
    Parses the Sarepta pipeline HTML and returns a list of serialized MasterTable-like objects.
    Mirrors the structure/logic of the reference script.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Sarepta pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Sarepta script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Get the “current as of” date from the <em> element
        date_last_updated = ""
        date_el = soup.select_one("p > em")
        if date_el:
            # e.g. "Information is current as of 6/27/2024, updates are made on a quarterly basis"
            date_last_updated = date_el.get_text(strip=True)

        # 2) Gather disclaimers (like ¹, ², ³) from BOTH the bottom paragraph AND the pipeline sections
        disclaimers_dict = {}

        # The bottom paragraph
        disclaimers_section = soup.select_one(".field--name-field-paragraph-cta-text p")

        # All pipeline sections
        pipeline_sections = soup.select("div.pipeline__section")

        # Build one big HTML string so we catch superscripts from both places
        disclaimers_html = ""
        if disclaimers_section:
            disclaimers_html += disclaimers_section.decode_contents()
        for section in pipeline_sections:
            # Append the raw HTML of each pipeline section so that footnotes in headings are captured
            disclaimers_html += section.decode_contents()

        # e.g. "¹<sub>Some text</sub>", "²<sub>Some other text</sub>"
        pattern = r'([\d¹²³⁴⁵⁶⁷⁸⁹]+)<sub>(.*?)</sub>'
        matches = re.findall(pattern, disclaimers_html)
        for sup, desc in matches:
            disclaimers_dict[sup] = desc.strip()

        # 3) Extract pipeline data
        treatments = []
        processed_treatments = set()

        # Now loop through each pipeline section
        for section in pipeline_sections:
            # Each "modality" is shown in .pipeline__standard
            modality_name_el = section.select_one(".pipeline__standard")
            if modality_name_el:
                modality_text = modality_name_el.get_text(strip=True)
            else:
                # fallback to data-standard-modality attribute
                modality_text = section.get("data-standard-modality", "").strip()

            # Collect disclaimers that appear in the modality text
            more_info_modality = []
            for sup_key, sup_val in disclaimers_dict.items():
                if sup_key in modality_text:
                    more_info_modality.append(sup_val)

            pipeline_rows = section.select(".pipeline-row")
            for row in pipeline_rows:
                try:
                    # Get row classes, parse out phase
                    row_class_list = row.get("class", [])
                    phase = parse_phase_from_class(row_class_list)
                    phase = clean_phase(phase)

                    # Drug name
                    drug_name_el = row.select_one(".pipeline__text")
                    drug_name = drug_name_el.get_text(strip=True) if drug_name_el else ""
                    drug_name = clean_text(drug_name)

                    # Indication
                    indication_el = row.select_one(".pipeline__phase-text span.pipeline-bar")
                    indication = indication_el.get_text(strip=True) if indication_el else ""
                    indication = clean_text(indication)

                    # Collect disclaimers from the drug name or indication
                    row_more_info = []
                    for sup_key, sup_val in disclaimers_dict.items():
                        if sup_key in drug_name or sup_key in indication:
                            row_more_info.append(sup_val)

                    # Combine disclaimers: modality-level + row-level
                    combined_more_info = []
                    combined_more_info.extend(more_info_modality)
                    combined_more_info.extend(row_more_info)
                    combined_more_info_str = "and ".join(combined_more_info) if combined_more_info else ""
                    combined_more_info_str = clean_text(combined_more_info_str)

                    # Build a final "description" or "target" string (similar to reference)
                    # Here, we just place the disclaimers (modality + row).
                    description_str = (
                        f"{combined_more_info_str}"
                    ).strip()
                    description_str = clean_text(description_str)

                    # ------ Multilingual data setup ------
                    # Indication
                    indication_translator = MultilingualData()
                    indication_translator.add_translation('en', indication)
                    indication_collection = MultilingualDataCollection()
                    indication_collection.add_data(indication_translator)

                    # Therapeutic area => We'll map to "modality" here
                    modality_translator = MultilingualData()
                    modality_translator.add_translation('en', modality_text)
                    modality_collection = MultilingualDataCollection()
                    modality_collection.add_data(modality_translator)

                    # Description => disclaimers, date, etc.
                    description_translator = MultilingualData()
                    description_translator.add_translation('en', description_str)
                    description_collection = MultilingualDataCollection()
                    description_collection.add_data(description_translator)


                    name_translator = MultilingualData()
                    name_translator.add_translation('en', drug_name)
                    name_collection = MultilingualDataCollection()
                    name_collection.add_data(name_translator)

                    phase_translator = MultilingualData()
                    phase_translator.add_translation("en", phase)
                    phase_collection = MultilingualDataCollection()
                    phase_collection.add_data(phase_translator)

                    date_updated_translator = MultilingualData()
                    date_updated_translator.add_translation("en", date_last_updated)
                    date_updated_collection = MultilingualDataCollection()
                    date_updated_collection.add_data(date_updated_translator)

                    # Generate identification key (company + drug name + indication + phase)
                    identification_key = generate_identification_key(
                        "Sarepta",
                        drug_name,
                        indication,
                        modality_text
                    )
                    date_scraped = datetime.now(timezone.utc)

                    # Build the key used to check duplicates
                    treatment_key = (drug_name, indication, phase, modality_text, description_str)

                    if treatment_key not in processed_treatments:
                        master_record = MasterTable(
                            company_name="Sarepta Therapeutics",
                            treatment_name=name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            therapeutic_area=modality_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            notes=description_collection.get_collection_as_json(),
                            identification_key=identification_key,
                            date_last_changed=date_updated_collection.get_collection_as_json(),
                            date_scraped=date_scraped
                        )
                        treatments.append(master_record.__dict__)
                        processed_treatments.add(treatment_key)

                except Exception as e:
                    logging.error(
                        f"Error processing row for {drug_name if 'drug_name' in locals() else 'unknown'}: {e}",
                        exc_info=True
                    )

        logging.info(f"Processed {len(treatments)} treatments for Sarepta.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Sarepta's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Sarepta script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []