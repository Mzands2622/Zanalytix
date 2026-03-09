from function_app import (
    fetch_with_zyte,
    clean_text,  # If you have a custom clean_text() available
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
async def fetch_ionis_html():
    """
    Returns the Ionis pipeline URL, mirroring the style of fetch_sanofi_html.
    """
    try:
        url = "https://www.ionis.com/science-and-innovation/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Ionis pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_ionis_html(html_content):
    """
    Parses Ionis' pipeline HTML and returns a list of serialized MasterTable objects.
    Adapts your current scraper logic, but wraps each record in MasterTable format
    and uses multilingual fields as in your reference scripts.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Ionis pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Ionis script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # ---------------------
        # 1) Find "Date Last Updated"
        #    e.g. "Ionis pipeline information updated as of November 6, 2024"
        # ---------------------
        date_last_updated = ""
        pipeline_container = soup.find("div", class_="pipeline__container")
        if pipeline_container:
            p_tag = pipeline_container.find("p")
            if p_tag and "Ionis pipeline information updated as of" in p_tag.get_text():
                text = p_tag.get_text(strip=True)
                match = re.search(r"as of (.+)$", text)
                if match:
                    date_last_updated = match.group(1).strip()

        # ---------------------
        # 2) Identify each major pipeline area: div.pipeline__item
        # ---------------------
        raw_rows = []

        pipeline_items = soup.find_all("div", class_="pipeline__item")
        for item in pipeline_items:
            # E.g. <h4>Neurology</h4>
            area_el = item.find("h4")
            if not area_el:
                continue
            therapeutic_area = area_el.get_text(strip=True)

            # The pipeline rows are inside div.pipeline-items__body > div.pipeline-item__body
            body_wrapper = item.find("div", class_="pipeline-items__body")
            if not body_wrapper:
                continue

            row_bodies = body_wrapper.find_all("div", class_="pipeline-item__body", recursive=False)
            for row_div in row_bodies:
                main_section = row_div.find("div", class_="pipeline-body__main")
                if not main_section:
                    continue

                # --- Program & Indication ---
                program_name = ""
                indication = ""
                name_div = main_section.find("div", class_="pipeline-body__name")
                if name_div:
                    # Program <h4>
                    h4_tag = name_div.find("h4")
                    if h4_tag:
                        program_name = h4_tag.get_text(strip=True)

                    # Indication is typically the last <p> in name_div
                    p_tags = name_div.find_all("p")
                    if p_tags:
                        indication = p_tags[-1].get_text(strip=True)

                # --- Partner ---
                partner_text = ""
                partner_div = main_section.find("div", class_="pipeline-body__partner")
                if partner_div:
                    p_tag_partner = partner_div.find("p")
                    if p_tag_partner:
                        partner_text = p_tag_partner.get_text(strip=True)

                # --- Phase ---
                phase_text = ""
                phase_div = main_section.find("div", class_="pipeline-body__phase")
                if phase_div:
                    indicator = phase_div.find("div", class_="pipeline-body__indicator")
                    if indicator and indicator.has_attr("data-phase"):
                        # e.g. data-phase="3" => "Phase 3"
                        phase_val = indicator["data-phase"]
                        phase_text = f"Phase {phase_val}"

                # --- More Info (expanded text) ---
                more_info_text = ""
                content_section = row_div.find("div", class_="pipeline-body__content")
                if content_section:
                    # Remove the "Close" button to avoid extraneous text
                    close_btn = content_section.find("button", class_="close")
                    if close_btn:
                        close_btn.extract()
                    more_info_text = content_section.get_text(" ", strip=True)

                raw_rows.append({
                    "TherapeuticArea": therapeutic_area,
                    "Program": program_name,
                    "Indication": indication,
                    "Partner": partner_text,
                    "Phase": phase_text,
                    "MoreInfo": more_info_text,
                    "DateLastUpdated": date_last_updated
                })

        # ---------------------
        # 3) Convert rows to MasterTable objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for row in raw_rows:
            area = clean_text(row["TherapeuticArea"]) if callable(clean_text) else row["TherapeuticArea"]
            program = clean_text(row["Program"]) if callable(clean_text) else row["Program"]
            indication = clean_text(row["Indication"]) if callable(clean_text) else row["Indication"]
            partner = clean_text(row["Partner"]) if callable(clean_text) else row["Partner"]
            phase = clean_phase(row["Phase"]) if callable(clean_phase) else row["Phase"]
            more_info = clean_text(row["MoreInfo"]) if callable(clean_text) else row["MoreInfo"]
            date_updated = row["DateLastUpdated"] or ""

            # Generate a unique identification key
            identification_key = generate_identification_key("Ionis", program, area, indication)

            # Build multilingual data for each field
            area_trans = MultilingualData()
            area_trans.add_translation("en", area)

            program_trans = MultilingualData()
            program_trans.add_translation("en", program)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", partner)

            more_info_trans = MultilingualData()
            more_info_trans.add_translation("en", more_info)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            date_updated_trans = MultilingualData()
            date_updated_trans.add_translation("en", date_last_updated)

            # Wrap them in collections
            area_collection = MultilingualDataCollection()
            program_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            date_updated_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            program_collection.add_data(program_trans)
            indication_collection.add_data(indication_trans)
            partner_collection.add_data(partner_trans)
            notes_collection.add_data(more_info_trans)
            phase_collection.add_data(phase_trans)
            date_updated_collection.add_data(date_updated_trans)

            # Build a unique tuple to avoid duplicates
            treatment_key = (area, program, indication, partner, phase, more_info)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Ionis Pharmaceuticals",
                    # We'll store 'program' as the treatment_name
                    treatment_name=program_collection.get_collection_as_json(),
                    # Indication, therapeutic_area, and phase as usual
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    # We can place 'partner' in 'target' or any field you prefer
                    partner=partner_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    # Use date_last_updated as date_last_changed
                    date_last_changed=date_updated_collection.get_collection_as_json(),
                    # MoreInfo goes into notes
                    notes=notes_collection.get_collection_as_json()
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Ionis.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Ionis's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Ionis script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []