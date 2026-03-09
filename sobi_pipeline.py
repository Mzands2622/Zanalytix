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


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_sobi_html():
    """
    Returns the Sobi pipeline URL.
    """
    try:
        url = "https://www.sobi.com/en/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Sobi pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_sobi_html(html_content):
    """
    Parses Sobi's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Sobi pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Sobi script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # ---------------------
        # Map Disease Areas
        # ---------------------
        area_map = {}
        legend_spans = soup.select('.legend .pipe-body span.item')
        for sp in legend_spans:
            cls_list = sp.get('class', [])
            text = sp.get_text(strip=True)
            for c in cls_list:
                if c.startswith('area'):
                    area_map[c] = text

        # ---------------------
        # Extract Pipeline Entries
        # ---------------------
        pipeline_data = []
        phase_cols = soup.select('.phases .row .col-12.col-lg')

        for col in phase_cols:
            phase_header = col.select_one('.phase-header h5')
            if not phase_header:
                continue
            phase_name = clean_text(phase_header.get_text(strip=True))

            phase_items_container = col.select_one('.phase-items')
            if not phase_items_container:
                continue

            phase_items = phase_items_container.select('.phase-item')
            for item in phase_items:
                all_classes = item.get('class', [])
                disease_area_class = next((cls for cls in all_classes if cls.startswith("area")), None)
                disease_area_text = clean_text(area_map.get(disease_area_class, ""))

                pipe_title = item.select_one('.pipe-body .pipe-title')
                drug_name = clean_text(pipe_title.get_text(strip=True)) if pipe_title else ""

                pipe_footer = item.select_one('.pipe-footer')
                indication = clean_text(pipe_footer.get_text(strip=True)) if pipe_footer else ""

                popup_id = None
                popup_trigger = item.select_one('.pipe[data-popup-id]')
                if popup_trigger:
                    popup_id = popup_trigger.get('data-popup-id')

                more_info = ""
                partner = ""

                if popup_id:
                    detail_popup = soup.select_one(f"div.popup#{popup_id}")
                    if detail_popup:
                        detail_col = detail_popup.select_one('.col-12.col-lg-8')
                        if detail_col:
                            paragraphs = detail_col.select('p')
                            if len(paragraphs) > 0:
                                more_info = clean_text(paragraphs[0].get_text(" ", strip=True))
                            if len(paragraphs) > 1:
                                partner = clean_text(paragraphs[1].get_text(" ", strip=True))

                pipeline_data.append({
                    "phase": phase_name,
                    "disease_area": disease_area_text,
                    "drug_name": drug_name,
                    "indication": indication,
                    "more_info": more_info,
                    "partner": partner
                })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            phase = clean_phase(entry["phase"])
            disease_area = clean_text(entry["disease_area"])
            drug_name = clean_text(entry["drug_name"])
            indication = clean_text(entry["indication"])
            more_info = clean_text(entry["more_info"])
            partner = clean_text(entry["partner"])

            identification_key = generate_identification_key("Sobi", drug_name, indication, disease_area)


            area_trans = MultilingualData()
            area_trans.add_translation("en", disease_area)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", partner)

            name_trans = MultilingualData()
            name_trans.add_translation("en", drug_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            # Collections
            area_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            info_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            indication_collection.add_data(indication_trans)
            info_collection.add_data(info_trans)
            partner_collection.add_data(partner_trans)
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (phase, disease_area, drug_name, indication, more_info, partner)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Sobi",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    notes=info_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Sobi.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Sobi's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Sobi script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []