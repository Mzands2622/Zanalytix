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
async def fetch_argenx_html():
    """
    Returns the Argenx pipeline URL.
    """
    try:
        url = "https://argenx.com/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Argenx pipeline URL: {e}")
        return None


# -----------------------
# Map Width to Phase
# -----------------------
def map_width_to_phase(width_str: str) -> str:
    """
    Converts a width style value (e.g., 'width:30%' ) to a textual pipeline stage.
    """
    match = re.search(r'width:(\d+)', width_str)
    if match:
        val = int(match.group(1))
        if val < 20:
            return "Preclinical"
        elif val < 40:
            return "Phase 1"
        elif val < 60:
            return "Proof of Concept"
        elif val < 80:
            return "Registrational"
        else:
            return "Commercial"
    return "Unknown"


# -----------------------
# Map Color to Therapeutic Area
# -----------------------
def map_color_to_therapeutic_area(classes) -> str:
    """
    Maps a color class from `disease-phase--color-XYZ` to a known therapeutic area.
    """
    color_map = {
        "neurology": "Neurology",
        "nephrology": "Nephrology",
        "hematology-rheumatology": "Hematology / Rheumatology",
        "dermatology": "Dermatology",
        "indication-not-disclosed": "Indication not disclosed"
    }
    for c in classes:
        if c.startswith("disease-phase--color-"):
            suffix = c.replace("disease-phase--color-", "")
            return color_map.get(suffix, "Unknown")
    return "Unknown"


# -----------------------
# Process HTML Function
# -----------------------
async def process_argenx_html(html_content):
    """
    Parses Argenx's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Argenx pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Argenx script returned no HTML content. Please investigate!"
            )
            return []
        soup = BeautifulSoup(html_content, "html.parser")
        final_data = []

        # 1) Each pipeline block
        pipeline_blocks = soup.select(".block-content.d-flex.flex-lg-row.flex-column")
        for block in pipeline_blocks:
            left_col = block.select_one(".block-col-first-left")
            if not left_col:
                continue

            # ------------------------------
            # A) Determine drug_name
            # ------------------------------
            title_el = left_col.select_one(".block-col-title")
            if title_el:
                # e.g. "Efgartigimod"
                raw_text = title_el.get_text(strip=True)
                drug_name = clean_text(raw_text)
            else:
                # fallback: <img> in .field--name-field-program-logo
                drug_name = None
                logo_div = left_col.select_one(".field--name-field-program-logo")
                if logo_div:
                    img_el = logo_div.select_one("img[alt]")
                    if img_el and "logo" not in img_el["alt"].lower():
                        alt_text = clean_text(img_el["alt"])
                        src_text = img_el.get("src", "").strip()

                        # Start with the alt text
                        drug_name = alt_text

                        # Check if src has something like "_Hytrulo"
                        match = re.search(r'vyvgart_(.*)\.webp', src_text, re.IGNORECASE)
                        if match:
                            extra_part = match.group(1)  # e.g. "Hytrulo"
                            if extra_part and (extra_part.lower() not in alt_text.lower()):
                                drug_name = f"{alt_text} {extra_part}".strip()

                if not drug_name:
                    drug_name = "Unknown"

            # ------------------------------
            # B) Grab the 'Target' text if present
            # ------------------------------
            block_target = left_col.select_one(".block-target .field-case-study-target")
            target = None
            if block_target:
                raw_target = block_target.get_text(separator=" ", strip=True)
                # remove the literal word "Target" or ":" if it exists
                cleaned_target = raw_target.replace("Target", "").replace(":", "").strip()
                target = clean_text(cleaned_target) if cleaned_target else None

            # ------------------------------
            # C) Indications in the Right Col
            # ------------------------------
            right_col = block.select_one(".block-col-last .field--name-field-items")
            if not right_col:
                continue

            disease_items = right_col.select(".paragraph--type--disease-phase")
            for item in disease_items:
                # 1) Indication text
                indication_el = item.select_one(".item-title span")
                if indication_el:
                    indication_raw = indication_el.get_text(strip=True)
                    indication_text = clean_text(indication_raw)
                else:
                    indication_text = "Unknown Indication"

                # 2) Phase from bar-desktop
                bar_desktop = item.select_one(".item-bar.bar-desktop")
                pipeline_stage = "Unknown"
                if bar_desktop and bar_desktop.has_attr("style"):
                    pipeline_stage = map_width_to_phase(bar_desktop["style"])
                    pipeline_stage = clean_phase(pipeline_stage)  # apply your standard "Phase X" cleaning if desired

                # 3) Therapeutic area from color
                bar_span = item.select_one("span.bar")
                therapeutic_area = "Unknown"
                if bar_span:
                    classes = bar_span.get("class", [])
                    therapeutic_area = map_color_to_therapeutic_area(classes)
                    therapeutic_area = clean_text(therapeutic_area)

                # 4) Country / flag image next to indication (if any)
                country_url = ""
                item_title_div = item.select_one(".item-title")
                if item_title_div:
                    flag_img_el = item_title_div.select_one("img")
                    if flag_img_el:
                        country_url = flag_img_el.get("src", "")

                # 5) Clinical trial logo (study) if present
                study_url = ""
                study_img_el = item.select_one(".clinical-trial-logo img")
                if study_img_el:
                    study_url = study_img_el.get("src", "")

                final_data.append({
                    "drug_name": drug_name,
                    "target": target,
                    "indication": indication_text,
                    "pipeline_stage": pipeline_stage,
                    "therapeutic_area": therapeutic_area,
                    "country": country_url,  # NEW
                    "study": study_url,      # NEW
                    "notes": ""
                })

        # 2) Partnered Section
        partnered_section = soup.select_one(".partnered-programs")
        if partnered_section:
            partnered_blocks = partnered_section.select(".block-content.block-content--center")
            for pb in partnered_blocks:
                # Attempt to get the target from .block-col-first-right
                target_el = pb.select_one(".block-col-first-right .field-case-study-target")
                partner_target = None
                if target_el:
                    raw_target = target_el.get_text(separator=" ", strip=True)
                    cleaned_target = raw_target.replace("Target", "").replace(":", "").strip()
                    partner_target = clean_text(cleaned_target)

                col_last = pb.select_one(".block-col-last")
                name, short_desc = None, None
                if col_last:
                    text_block = col_last.select_one(".field__item")
                    if text_block:
                        short_desc_raw = text_block.get_text(" ", strip=True)
                        short_desc = clean_text(short_desc_raw)
                        # Attempt to find something like "ARGX-111" in short_desc
                        dash_match = re.search(r"\b(\S*-\d+)\b", short_desc)
                        if dash_match:
                            name = dash_match.group(1).strip()
                        else:
                            # fallback to first sentence or first ~100 chars
                            name = short_desc.split(".")[0][:100]

                final_data.append({
                    "drug_name": name or "Unknown partner program",
                    "target": partner_target,
                    "indication": "Unknown",
                    "pipeline_stage": "Unknown",
                    "therapeutic_area": "Unknown",
                    "country": "",
                    "study": "",
                    "notes": short_desc or ""
                })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in final_data:
            drug_name = entry["drug_name"]
            target = entry["target"]
            indication = entry["indication"]
            pipeline_stage = entry["pipeline_stage"]
            therapeutic_area = entry["therapeutic_area"]
            country = entry["country"]
            study = entry["study"]
            notes = entry["notes"]

            # Generate the identification key
            identification_key = generate_identification_key("Argenx", drug_name, therapeutic_area, indication)

            # Build multilingual data
            target_trans = MultilingualData()
            target_trans.add_translation("en", target or "")

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes)

            drug_name_trans = MultilingualData()
            drug_name_trans.add_translation("en", drug_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", pipeline_stage)

            country_trans = MultilingualData()
            country_trans.add_translation("en", country)

            study_trans = MultilingualData()
            study_trans.add_translation("en", study)

            # Create collections
            target_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            area_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            drug_name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            country_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()

            # Add data to collections
            target_collection.add_data(target_trans)
            indication_collection.add_data(indication_trans)
            area_collection.add_data(area_trans)
            notes_collection.add_data(notes_trans)
            drug_name_collection.add_data(drug_name_trans)
            phase_collection.add_data(phase_trans)
            country_collection.add_data(country_trans)
            study_collection.add_data(study_trans)

            # Construct a unique key for duplicate checks
            treatment_key = (
                drug_name,
                target,
                indication,
                pipeline_stage,
                therapeutic_area,
                country,
                study,
                notes
            )

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Argenx",
                    treatment_name=drug_name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    target=target_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    country=country_collection.get_collection_as_json(),
                    study=study_collection.get_collection_as_json()
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Argenx.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Argenx's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Argenx script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []