from function_app import (
    fetch_with_zyte,
    clean_text,  # If you have a custom clean_text function
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
async def fetch_alnylam_html():
    """
    Returns the Alnylam pipeline URL, mirroring the style of fetch_sanofi_html.
    If you actually wanted to fetch the HTML directly here, you could do:
    html_content = await fetch_with_zyte(url)
    return html_content
    But as written, it just returns the URL.
    """
    try:
        url = "https://www.alnylam.com/alnylam-rnai-pipeline"
        logging.info(f"Fetching URL: {url}")
        return url
    except Exception as e:
        logging.error(f"Error fetching Alnylam pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_alnylam_html(html_content):
    """
    Parses Alnylam's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Alnylam pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Alnylam script returned no HTML content. Please investigate!"
            )
            return []

        logging.info("Parsing HTML content for Alnylam pipeline.")
        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Collect footnotes from <div class="pipeline-notes">
        logging.info("Collecting footnotes.")
        notes_div = soup.find("div", class_="pipeline-notes")
        footnotes_map = {}
        if notes_div:
            p_tags = notes_div.find_all("p")
            for p_tag in p_tags:
                sup_el = p_tag.find("sup")
                if sup_el and sup_el.text.strip():
                    sup_num = sup_el.text.strip()  # e.g. "1"
                    raw_text = p_tag.get_text(" ", strip=True)
                    cleaned_text = re.sub(r"^\s*\d+\s*", "", raw_text)
                    footnotes_map[sup_num] = cleaned_text
            logging.info(f"Collected footnotes: {footnotes_map}")

        # 2) Capture the "Date Last Updated" from <p class="final-note mt-16">
        logging.info("Capturing 'Date Last Updated'.")
        date_el = soup.find("p", class_="final-note mt-16")
        date_last_updated = date_el.get_text(strip=True) if date_el else ""
        logging.info(f"Date Last Updated: {date_last_updated}")

        # 3) Locate the main pipeline <section class="pipeline-section">
        logging.info("Locating the main pipeline section.")
        pipeline_section = soup.find("section", class_="pipeline-section")
        if not pipeline_section:
            logging.warning("No pipeline-section found.")
            return []

        # We'll collect raw row info here
        raw_rows = []

        # Each pipeline-category within the section
        categories = pipeline_section.find_all("div", class_="pipeline-category")
        logging.info(f"Found {len(categories)} pipeline categories.")
        for cat in categories:
            cat_title_el = cat.find(["h2", "div"], class_="category-title")
            if not cat_title_el:
                continue

            therapeutic_area = cat_title_el.get_text(strip=True)
            logging.info(f"Processing therapeutic area: {therapeutic_area}")

            table = cat.find("table")
            if not table:
                logging.info(f"No table found for therapeutic area: {therapeutic_area}")
                continue

            # IMPORTANT: Use find_all("tr") so we get rows in thead/tbody
            rows = table.find_all("tr")
            logging.info(f"Found {len(rows)} <tr> elements for: {therapeutic_area}")

            for row in rows:
                # Keep tds with recursive=False if you only want direct <td> children
                tds = row.find_all("td", recursive=False)
                if len(tds) < 3:
                    continue

                product_td = tds[0]
                disease_td = tds[1]
                phase_td = tds[2]

                product_text = product_td.get_text(" ", strip=True)
                disease_text = disease_td.get_text(" ", strip=True)
                phase_text = phase_td.get_text(" ", strip=True)

                # Extract any numeric footnote references
                sup_matches = re.findall(r"\b(\d+)\b", product_text + " " + disease_text)
                sup_matches = list(set(sup_matches))  # unique footnote numbers

                # Remove those digits from the displayed text
                product_clean = re.sub(r"\b(\d+)\b", "", product_text).strip()
                disease_clean = re.sub(r"\b(\d+)\b", "", disease_text).strip()

                # Map footnotes
                resolved_notes = [footnotes_map[num] for num in sup_matches if num in footnotes_map]

                raw_rows.append({
                    "TherapeuticArea": therapeutic_area,
                    "Program": product_clean,
                    "Indication": disease_clean,
                    "Phase": phase_text,
                    "Footnotes": resolved_notes,
                    "DateLastUpdated": date_last_updated
                })
            logging.info(f"Processed rows for therapeutic area: {therapeutic_area}")

        logging.info("Converting raw rows into MasterTable objects.")
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for row in raw_rows:
            # Apply your cleaning / normalization
            area = clean_text(row["TherapeuticArea"]) if callable(clean_text) else row["TherapeuticArea"]
            program = clean_text(row["Program"]) if callable(clean_text) else row["Program"]
            indication = clean_text(row["Indication"]) if callable(clean_text) else row["Indication"]
            phase = clean_phase(row["Phase"]) if callable(clean_phase) else row["Phase"]
            footnotes_list = row["Footnotes"] or []
            date_updated = row["DateLastUpdated"]

            # identification_key for deduplication
            identification_key = generate_identification_key("Alnylam", program, area, indication)

            # Prepare multilingual fields
            area_trans = MultilingualData()
            area_trans.add_translation("en", area)

            program_trans = MultilingualData()
            program_trans.add_translation("en", program)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", " | ".join(footnotes_list))

            date_last_updated_trans = MultilingualData()
            date_last_updated_trans.add_translation("en", date_updated)

            area_collection = MultilingualDataCollection()
            program_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            date_last_updated_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            program_collection.add_data(program_trans)
            indication_collection.add_data(indication_trans)
            phase_collection.add_data(phase_trans)
            notes_collection.add_data(notes_trans)
            date_last_updated_collection.add_data(date_last_updated_trans)

            # Deduplicate by some unique combination of fields
            treatment_key = (area, program, indication, phase)
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Alnylam Pharmaceuticals",
                    treatment_name=program_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    date_last_changed=date_last_updated_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json()
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Alnylam.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Alnylam's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Alnylam script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []