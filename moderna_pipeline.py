# moderna_pipeline.py

import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these imports to your actual project structure:
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

async def fetch_moderna_html():
    """
    Fetches the Moderna pipeline page using Zyte.
    """
    try:
        url = "https://www.modernatx.com/en-US/research/product-pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Moderna HTML: {e}")
        return None

async def process_moderna_html(html_content):
    """
    Parses the Moderna pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Moderna pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Moderna script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        all_records = []
        processed_entries = set()

        # We will collect both H2 and H3 headings in document order:
        #   - H2 => disease_area
        #   - H3 => therapeutic_area
        # Then parse pipeline items under each H3, attaching the current H2
        # as the broader disease_area context.
        headings_selector = (
            "h2.indexstyles__ModalityGroupHeading-sc-1mk3wkl-10.bhOLGy, "
            "h3.indexstyles__ModalityHeading-sc-1mk3wkl-11.iHVoBD"
        )
        headings_in_order = soup.select(headings_selector)

        current_disease_area = ""
        if not headings_in_order:
            logging.warning("No H2/H3 headings found on Moderna pipeline page.")
            send_sms(
                phone_number="9144334333",
                message="Moderna script found no headings. Please investigate!"
            )
            return []

        for heading in headings_in_order:
            # If this heading is an H2, it's our disease_area
            if heading.name == "h2":
                current_disease_area = heading.get_text(strip=True)
                continue

            # If heading is an H3, it's a sub therapeutic_area
            if heading.name == "h3":
                raw_therapeutic_area = heading.get_text(strip=True)

                # Pipeline items appear in the next <div> sibling
                pipeline_container = heading.find_next_sibling("div")
                if not pipeline_container:
                    continue

                # Each pipeline item is in a specific wrapper
                item_wrappers = pipeline_container.select(
                    "div.indexstyles__PipelineItemWrapper-sc-1mk3wkl-12.ISJjV"
                )

                for wrapper in item_wrappers:
                    data_divs = wrapper.select("div.indexstyles__PipelineItemData-sc-1mk3wkl-13.csUwmo")
                    phase_div = wrapper.select_one(
                        "div.indexstyles__PipelineItemPhaseMobile-sc-1mk3wkl-16.bFAxqP"
                    )
                    rights_div = wrapper.select_one(
                        "div.indexstyles__PipelineItemData-sc-1mk3wkl-13.dlULqK"
                    )

                    raw_indication = (
                        data_divs[0].get_text(strip=True) if len(data_divs) > 0 else ""
                    )
                    raw_treatment_name = (
                        data_divs[1].get_text(strip=True) if len(data_divs) > 1 else ""
                    )
                    raw_phase = phase_div.get_text(strip=True) if phase_div else ""
                    partner_text = rights_div.get_text(strip=True) if rights_div else ""

                    # Remove literal prefix "Moderna rights:"
                    raw_partner = partner_text.replace("Moderna rights:", "").strip()

                    # -------------------------
                    # 1) Clean text fields
                    # -------------------------
                    disease_area = clean_text(current_disease_area)
                    therapeutic_area = clean_text(raw_therapeutic_area)
                    indication = clean_text(raw_indication)
                    treatment_name = clean_text(raw_treatment_name)
                    phase = clean_phase(raw_phase)
                    partner = clean_text(raw_partner)

                    # -------------------------
                    # 2) Validate required fields (if necessary)
                    # -------------------------
                    # For instance, skip if no indication or treatment_name
                    if not indication and not treatment_name:
                        logging.warning(
                            "Skipping an entry due to missing indication and treatment name."
                        )
                        continue

                    # -------------------------
                    # 3) Generate identification key
                    # -------------------------
                    identification_key = generate_identification_key(
                        "Moderna",
                        treatment_name,
                        indication,
                        therapeutic_area
                    )

                    # -------------------------
                    # 4) Build multilingual data
                    # -------------------------
                    disease_area_data = MultilingualData()
                    therapeutic_area_data = MultilingualData()
                    indication_data = MultilingualData()
                    treatment_data = MultilingualData()
                    phase_data = MultilingualData()
                    partner_data = MultilingualData()

                    # Add English translations
                    disease_area_data.add_translation("en", disease_area)
                    therapeutic_area_data.add_translation("en", therapeutic_area)
                    indication_data.add_translation("en", indication)
                    treatment_data.add_translation("en", treatment_name)
                    phase_data.add_translation("en", phase)
                    partner_data.add_translation("en", partner)

                    # Create collections
                    disease_area_collection = MultilingualDataCollection()
                    therapeutic_area_collection = MultilingualDataCollection()
                    indication_collection = MultilingualDataCollection()
                    treatment_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()
                    partner_collection = MultilingualDataCollection()

                    disease_area_collection.add_data(disease_area_data)
                    therapeutic_area_collection.add_data(therapeutic_area_data)
                    indication_collection.add_data(indication_data)
                    treatment_collection.add_data(treatment_data)
                    phase_collection.add_data(phase_data)
                    partner_collection.add_data(partner_data)

                    # -------------------------
                    # 5) Create MasterTable record
                    # -------------------------
                    record_key = (
                        disease_area,
                        therapeutic_area,
                        indication,
                        treatment_name,
                        phase,
                        partner
                    )
                    if record_key not in processed_entries:
                        master_record = MasterTable(
                            company_name="Moderna",
                            # Basic fields
                            date_scraped=datetime.now(timezone.utc),
                            identification_key=identification_key,

                            # Multilingual fields
                            # (Add or remove as needed based on your data model)
                            disease_area=disease_area_collection.get_collection_as_json(),
                            therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            treatment_name=treatment_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            partner=partner_collection.get_collection_as_json()
                        )

                        all_records.append(master_record.__dict__)
                        processed_entries.add(record_key)

        logging.info(f"Processed {len(all_records)} pipeline items for Moderna.")
        return all_records

    except Exception as e:
        logging.error(f"An error occurred scraping Moderna's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Moderna's script: {e}. Please investigate!"
        )
        return []
