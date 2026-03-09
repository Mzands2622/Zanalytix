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
async def fetch_blueprint_html():
    """
    Returns the Blueprint Medicines pipeline URL.
    """
    try:
        url = "https://www.blueprintmedicines.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Blueprint Medicines pipeline URL: {e}")
        return None


# -----------------------
# Parse Superscript Legend
# -----------------------
async def scrape_superscript_legend(soup):
    """
    Extract legend text for each numeric superscript from the <section class="superscript-legend">.
    Returns a dictionary mapping e.g. '1' -> footnote text.
    """
    legend_section = soup.find("section", class_="superscript-legend")
    legend_map = {}

    if not legend_section:
        return legend_map

    ul = legend_section.find("ul", class_="list")
    if not ul:
        return legend_map

    for li in ul.find_all("li", class_="relative"):
        sup_tag = li.find("sup", class_="legend-superscript")
        if sup_tag:
            sup_number = sup_tag.get_text(strip=True)
            sup_tag.decompose()
            footnote_text = clean_text(li.get_text(strip=True))
            legend_map[sup_number] = footnote_text

    return legend_map


# -----------------------
# Parse Superscripts in Row
# -----------------------
def parse_superscript_in_row(row_tag, legend_map):
    """
    Identify footnotes in a row and return a list of footnote texts from legend_map.
    """
    row_sup_tags = row_tag.find_all("sup", style="font-size:0.65rem")
    footnotes_found = []

    for tag in row_sup_tags:
        text = tag.get_text(strip=True)
        references = [r.strip() for r in text.split(",")]
        for ref in references:
            if ref in legend_map:
                footnotes_found.append(legend_map[ref])

    return list(set(footnotes_found))


# -----------------------
# Extract Phase from TD
# -----------------------
def extract_phase_from_td(td_tag):
    """
    Extract and clean the phase text from a table cell.
    """
    if not td_tag:
        return None

    phase_span = td_tag.find("span", class_="o-0 dn")
    if phase_span:
        raw_phase = clean_text(phase_span.get_text(strip=True))
        phase_clean = re.sub(r"^\d+\s*", "", raw_phase).strip()
        return phase_clean or raw_phase
    else:
        raw_txt = td_tag.get_text(strip=True)
        if raw_txt:
            raw_txt_clean = clean_text(raw_txt)
            phase_clean = re.sub(r"^\d+\s*", "", raw_txt_clean).strip()
            return phase_clean or raw_txt_clean

    return None


# -----------------------
# Remove Trailing Phase
# -----------------------
def remove_trailing_phase(indication):
    """
    Remove trailing phase text from indication (e.g. "Phase 1" appended at the end).
    Adjust as needed if the source consistently follows a certain format.
    """
    new_text = re.sub(r"\d+\s*-\s*.*$", "", indication).strip()
    return new_text


# -----------------------
# Process HTML Function
# -----------------------
async def process_blueprint_html(html_content):
    """
    Parses Blueprint Medicines' pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Blueprint Medicines pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Blueprint Medicines script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Grab the superscript legend map
        legend_map = await scrape_superscript_legend(soup)
        
        # 2) Find all pipeline tables
        pipeline_tables = soup.find_all("table", class_="pipeline-table")
        all_records = []

        for pipeline_table in pipeline_tables:
            category = "Unknown Category"
            thead = pipeline_table.find("thead")
            if thead:
                first_th = (
                    thead.find("th", class_="medium-table-header") or
                    thead.find("th", class_="new-table-header") or
                    thead.find("th", class_="mobile-table-header")
                )
                if first_th:
                    cat_text = clean_text(first_th.get_text(strip=True))
                    if cat_text:
                        category = cat_text

            tbody = pipeline_table.find("tbody")
            if not tbody:
                continue

            current_program_name = None
            current_program_footnotes = []

            # 3) Each row in the table
            for tr in tbody.find_all("tr"):
                row_class = tr.get("class", [])

                # 3a) Program header row
                if "pipeline-table-row-header" in row_class:
                    program_td = tr.find("td", class_="molecular-target")
                    if program_td:
                        current_program_name = clean_text(program_td.get_text(strip=True))
                        current_program_footnotes = parse_superscript_in_row(program_td, legend_map)
                    else:
                        current_program_name = "Unknown Program"
                        current_program_footnotes = []

                    # Possibly there's a direct phase in the same row
                    phase_td = tr.find("td", class_="molecular-target-sort") \
                               or tr.find("td", class_="molecular-target-sort-secondary")
                    phase_text = extract_phase_from_td(phase_td) if phase_td else None

                    # Check the next sibling row to see if it has child rows
                    next_tr = tr.find_next_sibling("tr")
                    has_child = False
                    if next_tr:
                        next_class = next_tr.get("class", [])
                        if any("pipeline-table-row" in x for x in next_class):
                            has_child = True

                    # If there's no child row, we still need to store a record
                    if not has_child:
                        subcategory = "N/A"
                        treatment_name = current_program_name
                        if ":" in (current_program_name or ""):
                            parts = current_program_name.split(":", 1)
                            subcategory = parts[1].strip()
                            treatment_name = parts[0].strip()

                        # Clean the phase text
                        if phase_text:
                            phase_text = clean_phase(phase_text)

                        record = {
                            'Therapeutic Area': category,
                            'Subcategory': subcategory,
                            'Treatment Name': treatment_name,
                            'Indication': "N/A",
                            'Region': "N/A",
                            'Development Stage': phase_text if phase_text else "N/A"
                        }
                        record['Footnotes'] = current_program_footnotes or []
                            
                        all_records.append(record)

                # 3b) Child row(s) with actual indication & phase
                elif "pipeline-table-row" in row_class:
                    indication_td = tr.find("td", class_="molecular-target-secondary")
                    if indication_td:
                        row_footnotes = parse_superscript_in_row(indication_td, legend_map)
                        indication_text = clean_text(indication_td.get_text(strip=True))
                        indication_text = remove_trailing_phase(indication_text)
                    else:
                        indication_text = "Unknown Indication"
                        row_footnotes = []

                    phase_td = tr.find("td", class_="molecular-target-sort-secondary") \
                              or tr.find("td", class_="molecular-target-sort")
                    phase_text = extract_phase_from_td(phase_td) if phase_td else "N/A"

                    # Merge footnotes from program-level + row-level
                    combined_footnotes = list(set(current_program_footnotes + row_footnotes))

                    subcategory = "N/A"
                    treatment_name = current_program_name
                    if ":" in (current_program_name or ""):
                        parts = current_program_name.split(":", 1)
                        subcategory = parts[1].strip()
                        treatment_name = parts[0].strip()

                    # Clean the phase text
                    if phase_text:
                        phase_text = clean_phase(phase_text)
                        
                    record = {
                        'Therapeutic Area': category,
                        'Disease Area': subcategory,
                        'Treatment Name': treatment_name,
                        'Indication': indication_text,
                        'Development Stage': phase_text,
                        'Footnotes': combined_footnotes
                    }
                    all_records.append(record)

        # ---------------------------
        # 4) Convert raw records -> MasterTable
        # ---------------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in all_records:
            # Clean / unify fields
            # Ensure they are cleaned BEFORE generating the ID key
            therapeutic_area = clean_text(entry.get("Therapeutic Area", "Unknown"))
            treatment_name = clean_text(entry.get("Treatment Name", "Unknown"))
            indication = clean_text(entry.get("Indication", "Unknown"))
            development_stage = clean_phase(entry.get("Development Stage", "Unknown"))
            notes_joined = "; ".join(entry.get("Footnotes", []))
            notes_clean = clean_text(notes_joined)

            # If a separate disease_area field exists
            disease_area = clean_text(entry.get("Disease Area", "Unknown"))

            # Identification Key: built from cleaned text
            identification_key = generate_identification_key(
                "Blueprint Medicines",
                treatment_name,
                therapeutic_area,
                indication
            )

            # Multilingual Data
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            disease_trans = MultilingualData()
            disease_trans.add_translation("en", disease_area)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes_clean)

            treatment_name_trans = MultilingualData()
            treatment_name_trans.add_translation("en", treatment_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", development_stage)

            # Collections
            area_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            disease_collection = MultilingualDataCollection()
            treatment_name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            indication_collection.add_data(indication_trans)
            notes_collection.add_data(notes_trans)
            disease_collection.add_data(disease_trans)
            treatment_name_collection.add_data(treatment_name_trans)
            phase_collection.add_data(phase_trans)

            # Build unique key to avoid duplicates in final
            treatment_key = (
                therapeutic_area,
                treatment_name,
                indication,
                development_stage,
                notes_clean
            )

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Blueprint Medicines",
                    treatment_name=treatment_name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    disease_area=disease_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Blueprint Medicines.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Blueprint Medicines's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Blueprint Medicines script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []