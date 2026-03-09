from function_app import (
    fetch_with_zyte,        # same function or your own, as previously used
    clean_phase,
    clean_text,
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
async def fetch_astrazeneca_html():
    """
    Fetches the AstraZeneca pipeline HTML via Zyte.
    You can still decide to do it your original way (just returning the URL) or
    directly calling fetch_with_zyte here.
    """
    try:
        url = "https://www.astrazeneca.com/our-therapy-areas/pipeline.html"
        # Option 1: Just return the URL to be used later
        return url

        # Option 2 (direct fetch):
        # html_content = await fetch_with_zyte(url)
        # return html_content
    except Exception as e:
        logging.error(f"Error fetching AstraZeneca pipeline URL: {e}")
        return None


# -----------------------
# Internal Scraper Logic
# -----------------------
def scrape_astrazeneca_pipeline(html_content):
    """
    Takes the full HTML as a string and returns a list of dictionaries.
    Each dictionary can contain (depending on whether Active or Removed):
        - therapeutic_area
        - date_last_changed
        - phase
        - treatment_name
        - target
        - indication
        - phase_commencement_date
        - type_of_molecule
        - notes
        - Major_Market_Status
        - status_change
        - line_extension
        - reason_for_discontinuation
    ...plus any other fields you'd like.

    SPECIAL LOGIC for "First Major Market Filing Status":
      - If a <table class="pipeline__compound-detail-table"> is found, skip the first (header) row
        and gather non-empty <td> text from subsequent rows.
      - Join all non-empty cells with commas for each row, and semicolons across rows.
      - The final joined string becomes the value for "First Major Market Filing Status".
    """

    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    pipeline_data = []

    # A rename map for the active pipeline details
    detail_rename_map_active = {
        "Mechanism": "target",
        "Area under investigation": "indication",
        "Date commenced phase": "phase_commencement_date",
        "Molecule size": "type_of_molecule",
        "Additional information": "notes",
        "First Major Market Filing Status": "Major_Market_Status",  # new
        "Status change": "status_change",
    }

    # A rename map for the removed compounds
    detail_rename_map_removed = {
        "New/Line extension": "line_extension",
        "Area under investigation": "indication",
        "Reason for discontinuation": "reason_for_discontinuation",
        "Additional notes": "notes",
        "First Major Market Filing Status": "Major_Market_Status",
        "Status change": "status_change",
    }

    # Helper function to parse "First Major Market Filing Status" from a detail item
    def parse_major_market_status(detail_item_text, detail_item_element):
        """
        If the detail_item_text belongs to 'First Major Market Filing Status',
        look for an embedded table, skip the header row, gather text from <td>.
        Join row cells with a comma, join rows with semicolons.

        If no table is found, just return the cleaned text after removing the label.
        """
        table = detail_item_element.find("table", class_="pipeline__compound-detail-table")
        if table:
            rows = table.find_all("tr")
            collected_statuses = []
            for i, row in enumerate(rows):
                # skip row 0 if it's the header (Country / Date)
                if i == 0:
                    continue
                tds = row.find_all("td")
                # gather the text from each non-empty td
                row_texts = [td.get_text(strip=True) for td in tds if td.get_text(strip=True)]
                if row_texts:
                    # e.g. "Accepted", or "Submitted, Q4 2024"
                    joined = ", ".join(row_texts)
                    collected_statuses.append(joined)
            final_value = "; ".join(collected_statuses) if collected_statuses else ""
            return clean_text(final_value)
        else:
            # fallback: just remove the label from the front
            # e.g. "First Major Market Filing Status: Accepted"
            stripped = detail_item_text
            if stripped.startswith("First Major Market Filing Status"):
                # remove the label prefix
                stripped = stripped[len("First Major Market Filing Status") :].strip(": ")
            return clean_text(stripped)

    # ---- 1) SCRAPE ACTIVE PIPELINE --------------------------------------------------
    area_sections = soup.find_all("section", class_="pipeline__areas-region")

    for section in area_sections:
        h2_tag = section.find("h2", class_="pipeline__areas-title")
        if not h2_tag:
            continue

        full_title = h2_tag.get_text(strip=True)
        therapeutic_area = None
        date_last_changed = None

        # e.g. "Oncology (as of 12 November 2024)"
        match = re.match(r"(.*?)\((.*?)\)", full_title)
        if match:
            raw_area = match.group(1).strip()
            raw_date = match.group(2).strip()
            if raw_date.lower().startswith("as of"):
                raw_date = raw_date[5:].strip()
            therapeutic_area = clean_text(raw_area)
            date_last_changed = clean_text(raw_date)
        else:
            therapeutic_area = clean_text(full_title)

        # <div class="dual-tabs__panel pipeline__phases">
        phase_panels = section.find_all("div", class_="dual-tabs__panel pipeline__phases")
        for panel in phase_panels:
            phase_title_el = panel.find("h3", class_="pipeline__phase-title")
            if not phase_title_el:
                continue
            raw_phase = phase_title_el.get_text(strip=True)
            # e.g. "Phase I", "Phase II", "Phase III", or "LCM Projects"
            phase_name = clean_phase(raw_phase)

            # <ul class="pipeline__compounds"><li class="pipeline__compound">
            compounds = panel.select("ul.pipeline__compounds > li.pipeline__compound")
            for c in compounds:
                name_el = c.find("strong", class_="pipeline__compound-name")
                if not name_el:
                    continue
                treatment_name = clean_text(name_el.get_text(strip=True))

                # The details are in <div class="pipeline__compound-popup">
                popup_div = c.find("div", class_="pipeline__compound-popup")
                details_dict = {}
                if popup_div:
                    detail_items = popup_div.select("ul.pipeline__compound-details > li.pipeline__compound-detail")
                    for item in detail_items:
                        strong_tag = item.find("strong")
                        if not strong_tag:
                            continue

                        label = strong_tag.get_text(strip=True).replace(":", "")
                        strong_tag.extract()  # remove from item so we can get the rest
                        value_text = item.get_text(strip=True)

                        # Special check if label == "First Major Market Filing Status"
                        if label == "First Major Market Filing Status":
                            parsed_value = parse_major_market_status(value_text, item)
                            details_dict[label] = parsed_value
                        else:
                            details_dict[label] = clean_text(value_text)

                    # rename keys if present
                    for old_key, new_key in detail_rename_map_active.items():
                        if old_key in details_dict:
                            details_dict[new_key] = details_dict.pop(old_key)

                # Build final dictionary
                record = {
                    "therapeutic_area": therapeutic_area,
                    "date_last_changed": date_last_changed if date_last_changed else "Not specified",
                    "phase": phase_name,
                    "treatment_name": treatment_name,
                }
                record.update(details_dict)
                pipeline_data.append(record)

    # ---- 2) SCRAPE REMOVED (TERMINATED) PIPELINE ------------------------------------
    termination_section = soup.find("section", class_="l-constrained pipeline__terminations-region")
    if termination_section:
        ul_terminations = termination_section.find("ul", class_="pipeline__terminations")
        if ul_terminations:
            term_items = ul_terminations.find_all("li", class_="pipeline__termination")
            for t_item in term_items:
                name_el = t_item.find("strong", class_="pipeline__compound-name")
                if not name_el:
                    continue
                treatment_name = clean_text(name_el.get_text(strip=True))

                popup_div = t_item.find("div", class_="pipeline__compound-popup")
                details_dict = {}
                if popup_div:
                    detail_items = popup_div.select("ul.pipeline__compound-details > li.pipeline__compound-detail")
                    for detail_item in detail_items:
                        strong_tag = detail_item.find("strong")
                        if not strong_tag:
                            continue
                        label = strong_tag.get_text(strip=True).replace(":", "")
                        strong_tag.extract()
                        value_text = detail_item.get_text(strip=True)

                        # Again check "First Major Market Filing Status" table logic
                        if label == "First Major Market Filing Status":
                            parsed_value = parse_major_market_status(value_text, detail_item)
                            details_dict[label] = parsed_value
                        else:
                            details_dict[label] = clean_text(value_text)

                    # rename for removed items
                    for old_key, new_key in detail_rename_map_removed.items():
                        if old_key in details_dict:
                            details_dict[new_key] = details_dict.pop(old_key)

                record = {
                    "therapeutic_area": "Removed since last quarter",
                    "date_last_changed": "Not applicable",
                    "phase": "Removed",
                    "treatment_name": treatment_name,
                }
                record.update(details_dict)
                pipeline_data.append(record)

    return pipeline_data


# -----------------------
# Process HTML Function
# -----------------------
async def process_astrazeneca_html(html_content):
    """
    Parses the AstraZeneca pipeline HTML and returns a list of serialized MasterTable objects,
    reflecting all the new keys and the new logic for active + removed items.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for AstraZeneca pipeline.")
            send_sms(
                phone_number="9144334333",
                message="AstraZeneca script returned no HTML content. Please investigate!"
            )
            return []

        # 1) Scrape the pipeline into a list of dicts
        pipeline_data = scrape_astrazeneca_pipeline(html_content)
        logging.info(f"Scraped total {len(pipeline_data)} items (active + removed).")

        # 2) Build MasterTable objects for each pipeline record
        #    We want to unify the new fields:
        #      Major_Market_Status, status_change, date_last_changed, indication,
        #      line_extension, notes, phase, phase_commencement_date,
        #      reason_for_discontinuation, target, therapeutic_area,
        #      treatment_name, type_of_molecule
        #    + identification_key, date_scraped, etc.

        treatments = []
        processed_treatments = set()

        for item in pipeline_data:
            # Extract each field (some might not exist)
            therapeutic_area = item.get("therapeutic_area", "N/A")
            date_last_changed = item.get("date_last_changed", "N/A")
            phase = item.get("phase", "N/A")
            treatment_name = item.get("treatment_name", "N/A")
            target = item.get("target", "N/A")
            indication = item.get("indication", "N/A")
            phase_commencement_date = item.get("phase_commencement_date", "N/A")
            type_of_molecule = item.get("type_of_molecule", "N/A")
            notes = item.get("notes", "N/A")
            Major_Market_Status = item.get("Major_Market_Status", "N/A")
            status_change = item.get("status_change", "N/A")
            line_extension = item.get("line_extension", "N/A")
            reason_for_discontinuation = item.get("reason_for_discontinuation", "N/A")

            # identification_key
            identification_key = generate_identification_key(
                "AstraZeneca", therapeutic_area, treatment_name, indication
            )
            date_scraped = datetime.now(timezone.utc)

            # Build multilingual data objects
            area_translator = MultilingualData()
            date_last_changed_translator = MultilingualData()
            phase_translator = MultilingualData()
            treatment_name_translator = MultilingualData()
            target_translator = MultilingualData()
            indication_translator = MultilingualData()
            phase_commencement_date_translator = MultilingualData()
            type_of_molecule_translator = MultilingualData()
            notes_translator = MultilingualData()
            major_market_status_translator = MultilingualData()
            status_change_translator = MultilingualData()
            line_extension_translator = MultilingualData()
            reason_for_discontinuation_translator = MultilingualData()

            area_translator.add_translation("en", therapeutic_area)
            date_last_changed_translator.add_translation("en", date_last_changed)
            phase_translator.add_translation("en", phase)
            treatment_name_translator.add_translation("en", treatment_name)
            target_translator.add_translation("en", target)
            indication_translator.add_translation("en", indication)
            phase_commencement_date_translator.add_translation("en", phase_commencement_date)
            type_of_molecule_translator.add_translation("en", type_of_molecule)
            notes_translator.add_translation("en", notes)
            major_market_status_translator.add_translation("en", Major_Market_Status)
            status_change_translator.add_translation("en", status_change)
            line_extension_translator.add_translation("en", line_extension)
            reason_for_discontinuation_translator.add_translation("en", reason_for_discontinuation)

            # Build corresponding MultilingualDataCollections
            area_collection = MultilingualDataCollection()
            date_last_changed_collection = MultilingualDataCollection()
            phase_collection_obj = MultilingualDataCollection()
            treatment_name_collection = MultilingualDataCollection()
            target_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            phase_commencement_date_collection = MultilingualDataCollection()
            type_of_molecule_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            major_market_status_collection = MultilingualDataCollection()
            status_change_collection = MultilingualDataCollection()
            line_extension_collection = MultilingualDataCollection()
            reason_for_discontinuation_collection = MultilingualDataCollection()

            area_collection.add_data(area_translator)
            date_last_changed_collection.add_data(date_last_changed_translator)
            phase_collection_obj.add_data(phase_translator)
            treatment_name_collection.add_data(treatment_name_translator)
            target_collection.add_data(target_translator)
            indication_collection.add_data(indication_translator)
            phase_commencement_date_collection.add_data(phase_commencement_date_translator)
            type_of_molecule_collection.add_data(type_of_molecule_translator)
            notes_collection.add_data(notes_translator)
            major_market_status_collection.add_data(major_market_status_translator)
            status_change_collection.add_data(status_change_translator)
            line_extension_collection.add_data(line_extension_translator)
            reason_for_discontinuation_collection.add_data(reason_for_discontinuation_translator)

            unique_key = (treatment_name, indication, phase)
            if unique_key in processed_treatments:
                continue
            processed_treatments.add(unique_key)

            master_record = MasterTable(
                company_name="AstraZeneca",
                identification_key=identification_key,
                date_scraped=date_scraped,

                # The new fields, stored as JSON from your MultilingualDataCollections:
                therapeutic_area=area_collection.get_collection_as_json(),
                date_last_changed=date_last_changed_collection.get_collection_as_json(),
                phase=phase_collection_obj.get_collection_as_json(),
                treatment_name=treatment_name_collection.get_collection_as_json(),
                target=target_collection.get_collection_as_json(),
                indication=indication_collection.get_collection_as_json(),
                phase_commencement_date=phase_commencement_date_collection.get_collection_as_json(),
                type_of_molecule=type_of_molecule_collection.get_collection_as_json(),
                notes=notes_collection.get_collection_as_json(),
                major_market_status=major_market_status_collection.get_collection_as_json(),
                status_change=status_change_collection.get_collection_as_json(),
                line_extension=line_extension_collection.get_collection_as_json(),
                reason_for_discontinuation=reason_for_discontinuation_collection.get_collection_as_json()
            )

            treatments.append(master_record.__dict__)

        logging.info(f"Final compiled {len(treatments)} MasterTable records.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping AstraZeneca's Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in AstraZeneca script: {e}. Please investigate!"
        )
        return []
