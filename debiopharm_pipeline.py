import re
import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

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


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_debiopharm_html():
    """
    Returns the Debiopharm pipeline URL.
    """
    try:
        url = "https://www.debiopharm.com/drug-development/pipeline/#Infectious-disease"
        return url
    except Exception as e:
        logging.error(f"Error fetching Debiopharm pipeline URL: {e}")
        return None


# -----------------------
# Interpret Phase
# -----------------------
def interpret_phase(width_str: str) -> str:
    """
    Converts a width style string into a textual phase.
    """
    match = re.search(r'width:\s*(\d+)', width_str)
    if not match:
        return "Unknown"

    pct = int(match.group(1))
    if pct < 20:
        return "Discovery"
    elif pct < 40:
        return "Preclinical"
    elif pct < 60:
        return "Phase I"
    elif pct < 80:
        return "Phase II"
    else:
        return "Phase III"


# -----------------------
# Parse Legend
# -----------------------
def parse_legend(table_soup):
    """
    Builds a mapping of badge abbreviations to full descriptions.
    """
    legend_dict = {}

    legend_items = table_soup.select(".u-section-pipeline__table-legend__item")
    for item in legend_items:
        text_el = item.select_one(".u-section-pipeline__table-legend__item__text")
        if not text_el:
            continue

        span = text_el.select_one("span")
        if span:
            raw_key = span.get_text(strip=True)
            key = raw_key.rstrip(":").strip()
            full_text = text_el.get_text(strip=True)
            after_colon = full_text.replace(raw_key, "", 1).lstrip(":").strip()
            legend_dict[key] = after_colon

    return legend_dict


# -----------------------
# Process HTML Function
# -----------------------
async def process_debiopharm_html(html_content):
    """
    Parses Debiopharm's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Debiopharm pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Debiopharm script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        pipeline_sections = soup.select("section.u-section.u-section-pipeline")
        pipeline_data = []

        for section in pipeline_sections:
            # Category name (e.g., "Oncology", "Infectious disease")
            header_el = section.select_one("h3.u-section-pipeline__title")
            raw_category_name = header_el.get_text(strip=True) if header_el else "Unknown Category"
            category_name = clean_text(raw_category_name)

            # Map any special "badges" from legend
            legend_map = parse_legend(section)

            table = section.select_one(".u-section-pipeline__table")
            if not table:
                continue

            rows = table.select(".u-section-pipeline__table__row")
            for row in rows:
                indication_inners = row.select(".u-section-pipeline__table__row__inner--indications")
                if not indication_inners:
                    continue

                for iblock in indication_inners:
                    # Program name
                    name_el = iblock.select_one(".u-section-pipeline__table__col.u-section-pipeline__table__col__name")
                    raw_program_name = name_el.get_text(strip=True) if name_el else ""
                    program_name = clean_text(raw_program_name.lstrip("_").strip())

                    # Indication
                    indication_el = iblock.select_one(".u-section-pipeline__table__col__indication")
                    raw_indication = indication_el.get_text(strip=True) if indication_el else ""
                    indication = clean_text(raw_indication)

                    # Mode of action (target)
                    moa_el = iblock.select_one(".u-section-pipeline__table__col__compound_name")
                    raw_mode_of_action = moa_el.get_text(strip=True) if moa_el else ""
                    mode_of_action = clean_text(raw_mode_of_action)

                    # Pipeline phase
                    phase_el = iblock.select_one(".u-section-pipeline__table__col__phase .line")
                    raw_pipeline_stage = "Unknown"
                    if phase_el and 'style' in phase_el.attrs:
                        raw_pipeline_stage = interpret_phase(phase_el['style'])
                    pipeline_stage = clean_phase(raw_pipeline_stage)

                    # Additional info (badges)
                    badge_el = iblock.select_one(".u-section-pipeline__table__col__labels .badge")
                    more_info = ""
                    if badge_el:
                        badge_text = badge_el.get_text(strip=True)
                        parts = [x.strip() for x in badge_text.split("/")]
                        mapped_parts = [legend_map.get(p, p) for p in parts]
                        more_info = "; ".join(mapped_parts)

                    more_info = clean_text(more_info)

                    # Build a record
                    pipeline_data.append({
                        "category": category_name,
                        "program_name": program_name,
                        "indication": indication,
                        "target": mode_of_action,
                        "pipeline_stage": pipeline_stage,
                        "more_info": more_info
                    })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            category = entry["category"]
            program_name = entry["program_name"]
            indication = entry["indication"]
            target = entry["target"]
            pipeline_stage = entry["pipeline_stage"]
            more_info = entry["more_info"]

            # Generate identification key
            identification_key = generate_identification_key(
                "Debiopharm",
                program_name,
                indication,
                target
            )

            # Prepare multilingual data
            category_trans = MultilingualData()
            category_trans.add_translation("en", category)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            target_trans = MultilingualData()
            target_trans.add_translation("en", target)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)

            name_trans = MultilingualData()
            name_trans.add_translation("en", program_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", pipeline_stage)

            # Collections
            category_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            target_collection = MultilingualDataCollection()
            info_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            category_collection.add_data(category_trans)
            indication_collection.add_data(indication_trans)
            target_collection.add_data(target_trans)
            info_collection.add_data(info_trans)
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (
                category,
                program_name,
                indication,
                target,
                pipeline_stage,
                more_info
            )

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Debiopharm",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=category_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    target=target_collection.get_collection_as_json(),
                    notes=info_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Debiopharm.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Debiopharm's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Debiopharm script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []