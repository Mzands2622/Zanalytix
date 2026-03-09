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
async def fetch_apellis_html():
    """
    Returns the Apellis pipeline URL.
    """
    try:
        url = "https://apellis.com/our-science/our-pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Apellis pipeline URL: {e}")
        return None

# -----------------------
# Parse Disclaimers
# -----------------------
def parse_disclaimers(footnotes_text):
    """
    Parses disclaimers for lines starting with * or ** and captures them in a dictionary.
    """
    disclaimers_map = {}
    pattern = r'(\*+)([^\*]+)'
    for match in re.finditer(pattern, footnotes_text):
        star_str = match.group(1)
        text_str = match.group(2).strip()
        disclaimers_map[star_str] = text_str
    return disclaimers_map


# -----------------------
# Process HTML Function
# -----------------------
async def process_apellis_html(html_content):
    """
    Parses Apellis' pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Apellis pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Apellis script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_data = []

        footnotes_el = soup.select_one("p.c-pipeline__smallprint")
        footnotes_text = footnotes_el.get_text(" ", strip=True) if footnotes_el else ""
        disclaimers_map = parse_disclaimers(footnotes_text)

        pipeline_items = soup.select("div.c-pipeline__item")
        for item in pipeline_items:
            area_title_el = item.select_one("h2.c-pipeline__title")
            therapeutic_area = clean_text(area_title_el.get_text(strip=True)) if area_title_el else ""

            rows = item.select(".c-pipeline__row:not(.c-pipeline__row--head)")
            for row in rows:
                product_el = row.select_one(".c-pipeline__product")
                product_text = clean_text(product_el.get_text(" ", strip=True)) if product_el else ""

                trailing_stars = "**" if product_text.endswith("**") else "*" if product_text.endswith("*") else None

                disease_blocks = row.select(".c-pipeline__disease")
                if not disease_blocks:
                    pipeline_data.append({
                        "therapeutic_area": therapeutic_area,
                        "product": product_text,
                        "disease": "",
                        "phase": "",
                        "more_info": ""
                    })
                    continue

                for disease_block in disease_blocks:
                    disease_name_el = disease_block.select_one("strong")
                    disease_name = clean_text(disease_name_el.get_text(strip=True)) if disease_name_el else ""

                    phase_el = disease_block.select_one("span.c-pipeline__phase")
                    phase_text = clean_phase(phase_el.get_text(strip=True)) if phase_el else ""

                    more_info = ""
                    em_el = disease_block.select_one("em")
                    if em_el:
                        span_phase = em_el.select_one("span.c-pipeline__phase")
                        if span_phase:
                            span_phase.extract()
                        more_info = clean_text(em_el.get_text(strip=True))

                    if trailing_stars and trailing_stars in disclaimers_map:
                        disclaim_text = disclaimers_map[trailing_stars]
                        more_info = f"{more_info} | {disclaim_text}" if more_info else disclaim_text

                    pipeline_data.append({
                        "therapeutic_area": therapeutic_area,
                        "product": product_text,
                        "disease": disease_name,
                        "phase": phase_text,
                        "more_info": more_info
                    })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            therapeutic_area = entry["therapeutic_area"]
            product = entry["product"]
            disease = entry["disease"]
            phase = entry["phase"]
            more_info = entry["more_info"]

            identification_key = generate_identification_key("Apellis", product, therapeutic_area, disease)

            # Multilingual Data
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            disease_trans = MultilingualData()
            disease_trans.add_translation("en", disease)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)

            product_trans = MultilingualData()
            product_trans.add_translation("en", product)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            # Collections
            area_collection = MultilingualDataCollection()
            disease_collection = MultilingualDataCollection()
            info_collection = MultilingualDataCollection()
            product_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            disease_collection.add_data(disease_trans)
            info_collection.add_data(info_trans)
            product_collection.add_data(product_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (therapeutic_area, product, disease, phase, more_info)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Apellis Pharmaceuticals",
                    treatment_name=product_collection.get_collection_as_json(),
                    indication=disease_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    notes=info_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Apellis.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Apellis's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Apellis script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []


