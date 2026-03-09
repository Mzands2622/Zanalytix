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
from bs4 import BeautifulSoup, NavigableString
import logging

# --------------------------------------
# 1) fetch_agenus_html() – returns URL
# --------------------------------------
async def fetch_agenus_html():
    """
    Return the URL for Agenus pipeline.
    (Similar to the reference's fetch_jazz_html.)
    """
    try:
        url = "https://agenusbio.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Agenus pipeline URL: {e}")
        return None


# ------------------------------------------------
# 2) parse_pipeline_sections() – the core logic
# ------------------------------------------------
def parse_pipeline_sections(soup):
    """
    Returns a list of dicts, each with:
      treatment_name, target, partner, partner_images, phase, indication
    Where:
      - 'partner' is the nearest H2 heading
      - 'partner_images' is a list of any text/img alt found in the 3rd column
    """
    results = []
    current_partner = None

    all_headings_and_rows = soup.select(
        "div.elementor-widget-heading, div.e-loop-item.pipeline"
    )

    for item in all_headings_and_rows:
        # 1) Check if it’s a heading <h2 class="elementor-heading-title">…</h2>
        possible_h2 = item.select_one("h2.elementor-heading-title")
        if possible_h2 is not None:
            current_partner = possible_h2.get_text(strip=True)
            continue

        # 2) If it’s a pipeline row
        if "e-loop-item" in item.get("class", []) and "pipeline" in item.get("class", []):
            columns = item.select("div.elementor-column.elementor-col-20")
            if len(columns) < 4:
                continue

            # (A) treatment_name
            product_el = columns[0].select_one(".elementor-widget-text-editor")
            treatment_name = product_el.get_text(strip=True) if product_el else ""

            # (B) target
            target_el = columns[1].select_one(".elementor-widget-text-editor")
            target = target_el.get_text(strip=True) if target_el else ""

            # (C) partner_images = a list of strings from the 3rd column
            partner_el = columns[2]
            partner_items = []

            txt_els = partner_el.select(".elementor-widget-text-editor")
            for t_el in txt_els:
                txt_str = t_el.get_text(strip=True)
                if txt_str:
                    partner_items.append(txt_str)

            imgs = partner_el.select("img")
            for img in imgs:
                # If alt text is present, use that; otherwise fallback to src
                if img.get("alt"):
                    partner_items.append(img["alt"])
                elif img.get("src"):
                    partner_items.append(img["src"])

            partner_images = partner_items

            # (D) "partner" = last heading
            heading_partner = current_partner

            # (E) Phase
            phase_el = columns[3].select_one(".elementor-heading-title")
            phase = phase_el.get_text(strip=True) if phase_el else ""

            # (F) Indication
            indication_el = columns[3].select_one(".elementor-widget-progress .elementor-title")
            indication = indication_el.get_text(strip=True) if indication_el else ""

            # Build final row dict
            entry = {
                "treatment_name": treatment_name,
                "target": target,
                "partner": heading_partner,
                "partner_images": partner_images,  # keep as list
                "phase": phase,
                "indication": indication,
            }
            results.append(entry)

    return results


# ------------------------------------------------
# 3) process_agenus_html(html_content)
# ------------------------------------------------
async def process_agenus_html(html_content):
    """
    Receives the raw HTML for Agenus pipeline,
    parses it, builds MasterTable objects,
    and returns them. 

    We DO include identification_key and date_scraped,
    but we do NOT store them as multilingual.
    partner_images remains a list (not joined).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Agenus pipeline.")
            # Optionally send an SMS
            send_sms(
                phone_number="9144334333",
                message="Agenus pipeline script returned no HTML content. Please investigate!"
            )
            return []

        # Step 1: parse soup
        soup = BeautifulSoup(html_content, "html.parser")
        # Step 2: get row dicts from parse_pipeline_sections
        raw_rows = parse_pipeline_sections(soup)

        # Prepare final results
        final_treatments = []
        processed_keys = set()

        # We'll add date_scraped to each record
        date_scraped = datetime.now(timezone.utc)

        for row in raw_rows:
            # Extract raw strings
            raw_treatment = row.get("treatment_name", "")
            raw_target = row.get("target", "")
            raw_partner = row.get("partner", "")
            raw_images = row.get("partner_images", [])  # a list
            raw_phase = row.get("phase", "")
            raw_indication = row.get("indication", "")

            # Clean them
            cleaned_treatment = clean_text(raw_treatment)
            cleaned_target = clean_text(raw_target)
            cleaned_partner = clean_text(raw_partner)
            # partner_images is a list, let's keep it as a list (no join)
            partner_images_list = clean_text(str(raw_images))
            # Phase might want special cleaning
            cleaned_phase = clean_phase(raw_phase)
            # Indication
            cleaned_indication = clean_text(raw_indication)

            # 1) Create multilingual fields (like your reference):
            #    we assume MasterTable has these fields
            #    (treatment_name, target, partner, partner_images, phase, indication)
            treatment_data = MultilingualData()
            treatment_data.add_translation("en", cleaned_treatment)

            target_data = MultilingualData()
            target_data.add_translation("en", cleaned_target)

            partner_data = MultilingualData()
            partner_data.add_translation("en", cleaned_partner)

            # For partner_images (the user wants it as a list, 
            # so let's store it in the MasterTable as a python list. 
            # If your MasterTable demands a string, you'd do e.g. JSON-serialize it. 
            # But we assume it can handle a list.

            phase_data = MultilingualData()
            phase_data.add_translation("en", cleaned_phase)

            indication_data = MultilingualData()
            indication_data.add_translation("en", cleaned_indication)

            # Convert each to a collection
            treatment_collection = MultilingualDataCollection()
            treatment_collection.add_data(treatment_data)

            target_collection = MultilingualDataCollection()
            target_collection.add_data(target_data)

            partner_collection = MultilingualDataCollection()
            partner_collection.add_data(partner_data)

            phase_collection = MultilingualDataCollection()
            phase_collection.add_data(phase_data)

            indication_collection = MultilingualDataCollection()
            indication_collection.add_data(indication_data)

            # 2) Build identification_key. 
            #    For example, you might do "Agenus", plus some combination of fields:
            identification_key = generate_identification_key(
                "Agenus",
                cleaned_treatment,
                cleaned_target,
                cleaned_indication
            )

            # 3) Deduplicate
            #    We'll define a row_key that includes the text plus the images
            row_key = (
                cleaned_treatment,
                cleaned_target,
                cleaned_partner,
                cleaned_phase,
                cleaned_indication
            )
            if row_key in processed_keys:
                continue  # skip duplicate
            processed_keys.add(row_key)

            # 4) Construct the MasterTable object
            #    We do pass identification_key and date_scraped 
            #    (non-multilingual)
            record = MasterTable(
                company_name="Agenus",
                treatment_name=treatment_collection.get_collection_as_json(),
                target=target_collection.get_collection_as_json(),
                partner=partner_collection.get_collection_as_json(),
                partner_images=partner_images_list,  # keep as list
                phase=phase_collection.get_collection_as_json(),
                indication=indication_collection.get_collection_as_json(),
                identification_key=identification_key,
                date_scraped=date_scraped
            )

            # 5) Append its __dict__ or the object itself 
            #    (the reference script uses .__dict__)
            final_treatments.append(record.__dict__)

        logging.info(f"Agenus: created {len(final_treatments)} records with date_scraped + ID key.")
        return final_treatments

    except Exception as e:
        logging.error(f"Error scraping Agenus pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Agenus pipeline script: {e}. Please investigate!"
        )
        return []
