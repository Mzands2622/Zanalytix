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

# -----------------------------------
# (Optional) Mapping of known sponsor images to text
# If you have more images -> text mappings, add them here.
# -----------------------------------
SPONSOR_IMAGE_MAP = {
    "jhm_logo": "Johns Hopkins University",  # Example
    # Add more if needed...
}


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_macrogenics_html():
    """
    Returns the MacroGenics pipeline URL.
    """
    try:
        url = "https://macrogenics.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching MacroGenics pipeline URL: {e}")
        return None


# -----------------------
# Parse Disclaimers
# -----------------------
def parse_disclaimers(soup):
    """
    Extract disclaimers from the <ol type="a" class="disclaimer"> block.
    Returns a dictionary mapping letters to disclaimer text.
    """
    disclaimer_dict = {}
    disclaimers_section = soup.select_one('ol.disclaimer')
    if disclaimers_section:
        items = disclaimers_section.find_all('li')
        for i, li in enumerate(items):
            letter_key = chr(ord('a') + i)
            text = clean_text(li.get_text(strip=True))
            disclaimer_dict[letter_key] = text
    return disclaimer_dict


# -----------------------
# Extract Superscript References
# -----------------------
def extract_superscript_references(element):
    """
    Extract superscript references like <sup>(a)</sup> from the given element.
    Returns a list of found letters.
    """
    refs = []
    if not element:
        return refs
    sup_tags = element.find_all('sup')
    for s in sup_tags:
        text = s.get_text(strip=True).lower()
        matches = re.findall(r"\((\w)\)", text)
        for m in matches:
            refs.append(m.lower())
    return refs


# -----------------------
# Get Highest Phase
# -----------------------
def get_highest_phase(div_placeholder):
    """
    Deduce the phase from the 'width: XX%' style or presence of 'Marketed'.
    """
    if not div_placeholder:
        return None

    style_val = div_placeholder.get("style", "")
    match = re.search(r'width:\s?(\d+)%', style_val)
    if match:
        width_num = int(match.group(1))
        if width_num >= 100:
            return "Marketed"
        elif width_num >= 75:
            return "Phase 3"
        elif width_num >= 50:
            return "Phase 2"
        elif width_num >= 25:
            return "Phase 1"
        else:
            return "Preclinical"

    text_content = div_placeholder.get_text(strip=True).lower()
    if "marketed" in text_content:
        return "Marketed"
    return None


# -----------------------
# Parse Table
# -----------------------
def parse_table(table, disclaimers, therapeutic_area=None):
    """
    Parse each row in the pipeline table.
    Handles rowspan to produce multiple entries.
    Also includes logic to extract sponsor name from <img> tags and alt text.
    """
    results = []
    rows = table.select('tbody > tr')
    i = 0
    while i < len(rows):
        row = rows[i]
        # Skip "separator" rows
        if 'sep-row' in row.get('class', []):
            i += 1
            continue

        title_cell = row.select_one('td.title')
        if title_cell:
            # Handle rowspan to link multiple indications / sub-rows
            rowspan = title_cell.get('rowspan')
            span_count = int(rowspan) if (rowspan and rowspan.isdigit()) else 1

            # Extract the main treatment name from the title cell
            raw_title_text = clean_text(title_cell.get_text(" ", strip=True))
            treatment_name = raw_title_text

            # Superscript disclaimers found in the title cell
            sup_in_title = extract_superscript_references(title_cell)

            # Loop over sub-rows for multiple indications
            for sub_index in range(span_count):
                current_row_index = i + sub_index
                if current_row_index >= len(rows):
                    break

                sub_row = rows[current_row_index]
                # If we hit another separator row, break out
                if 'sep-row' in sub_row.get('class', []):
                    break

                # Extract Indication & Modality from td.subtitle
                sub_tds = sub_row.select('td.subtitle')
                indication, modality = "", ""
                if len(sub_tds) == 2:
                    indication, modality = map(
                        clean_text,
                        [td.get_text(" ", strip=True) for td in sub_tds]
                    )
                elif len(sub_tds) == 1:
                    indication = clean_text(sub_tds[0].get_text(" ", strip=True))

                # Also gather disclaimers from sub-titles
                sub_refs = []
                for td_ in sub_tds:
                    sub_refs.extend(extract_superscript_references(td_))

                # --------------------------------------------------------
                # PHASE EXTRACTION
                # --------------------------------------------------------
                placeholder_div = sub_row.select_one('div.placeholder')
                phase_value = clean_phase(get_highest_phase(placeholder_div))

                # NEW: Capture any extra text inside <div>...<div> within the placeholder
                extra_phase_text = ""
                if placeholder_div:
                    child_div = placeholder_div.find('div')  # e.g. <div>IND submitted</div>
                    if child_div:
                        extra_phase_text = clean_text(child_div.get_text(strip=True))

                pipeline_item = {
                    "Therapeutic Area": therapeutic_area or "Oncology/Partnered",
                    "Treatment Name": treatment_name,
                    "Indication": indication,
                    "Modality": modality,
                    "Phase": phase_value,
                    "Partner": "",
                    "More Info": []
                }

                # Combine disclaimers from the main title and sub-row
                disclaimers_found = set(sup_in_title + sub_refs)
                for letter in disclaimers_found:
                    if letter in disclaimers:
                        pipeline_item["More Info"].append(disclaimers[letter])

                # Append the extra phase text to More Info if present
                if extra_phase_text:
                    pipeline_item["More Info"].append(extra_phase_text)

                # Extract Sponsor/Partner logic
                rights_cell = sub_row.select_one('td.rights')
                if rights_cell:
                    sponsor_text_parts = []
                    sponsor_raw_text = clean_text(rights_cell.get_text(" ", strip=True))

                    # 1) Check for <img> alt or src
                    sponsor_imgs = rights_cell.select('img')
                    for img in sponsor_imgs:
                        alt_val = img.get('alt', '').strip()
                        # Remove "logo" if present in alt text
                        alt_val = re.sub(r'\s*logo\s*', '', alt_val, flags=re.IGNORECASE).strip()

                        # If alt text is empty, fall back to checking the src
                        if not alt_val:
                            src_val = img.get('src', '')
                            for key, val in SPONSOR_IMAGE_MAP.items():
                                if key.lower() in src_val.lower():
                                    alt_val = val
                                    break

                        if alt_val:
                            sponsor_text_parts.append(alt_val)

                    # 2) Check for <span class="pipeline-text rights-text">
                    span_rights_text = rights_cell.select_one('span.pipeline-text.rights-text')
                    if span_rights_text:
                        sponsor_text_parts.append(
                            clean_text(span_rights_text.get_text(" ", strip=True))
                        )

                    # 3) Use any raw text if it's not empty
                    if sponsor_raw_text:
                        sponsor_text_parts.append(sponsor_raw_text)

                    # Remove duplicates & join
                    sponsor_text_parts = list(dict.fromkeys([p for p in sponsor_text_parts if p]))
                    pipeline_item["Partner"] = " | ".join(sponsor_text_parts)

                results.append(pipeline_item)

            i += span_count
        else:
            i += 1

    return results


# -----------------------
# Process HTML Function
# -----------------------
async def process_macrogenics_html(html_content):
    """
    Parses MacroGenics' pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Macrogenics pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Macrogenics script returned no HTML content. Please investigate!"
            )
            return []
        soup = BeautifulSoup(html_content, "html.parser")

        # --------------------------------------------------
        # 1) SCRAPE THE "as of XXX" TEXT INTO A VARIABLE
        # --------------------------------------------------
        date_last_updated = None
        # Example: <p class="">MacroGenics ... (as of April 2024)</p>
        overview_paragraph = soup.find(
            "p",
            string=re.compile(r"MacroGenics has a diverse portfolio", re.IGNORECASE)
        )
        if overview_paragraph:
            text_content = overview_paragraph.get_text(strip=True)
            # e.g. "... (as of April 2024)"
            match_parenthetical = re.search(r"\(as of ([^)]+)\)", text_content, re.IGNORECASE)
            if match_parenthetical:
                # group(1) will contain just the text after "as of", without parentheses
                date_last_updated = f"as of {match_parenthetical.group(1)}"


        # Parse disclaimers
        disclaimers_dict = parse_disclaimers(soup)

        # Identify main and partnered tables
        main_table = soup.select_one('table.pipeline-table.pipeline-table-desktop:not(.ppl2)')
        partnered_table = soup.select_one('table.pipeline-table.pipeline-table-desktop.ppl2')

        all_results = []
        if main_table:
            oncology_results = parse_table(main_table, disclaimers_dict, "Oncology")
            all_results.extend(oncology_results)

        if partnered_table:
            partnered_results = parse_table(partnered_table, disclaimers_dict, "Partnered Programs")
            all_results.extend(partnered_results)

        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # --------------------------------------------------
        # 2) CONVERT THE PIPELINE ITEM DICTS INTO MASTERTABLE OBJECTS
        # --------------------------------------------------
        for entry in all_results:
            therapeutic_area = clean_text(entry.get("Therapeutic Area", "Unknown"))
            treatment_name = clean_text(entry.get("Treatment Name", "Unknown"))
            indication = clean_text(entry.get("Indication", "Unknown"))
            phase = clean_phase(entry.get("Phase", "Unknown"))
            partner = clean_text(entry.get("Partner", "Unknown"))
            modality = clean_text(entry.get("Modality", "Unknown"))

            # Combine disclaimers, references, etc. into "notes"
            notes = "; ".join(entry.get("More Info", []))
            notes = clean_text(notes)

            # Generate a unique key
            identification_key = generate_identification_key(
                "MacroGenics",
                treatment_name,
                indication,
                modality
            )

            # Create multilingual data objects
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            modality_trans = MultilingualData()
            modality_trans.add_translation("en", modality)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", partner)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes)

            name_trans = MultilingualData()
            name_trans.add_translation("en", treatment_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            date_updated_trans = MultilingualData()
            date_updated_trans.add_translation("en", date_last_updated)

            # Create collections
            area_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            modality_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            date_updated_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            indication_collection.add_data(indication_trans)
            partner_collection.add_data(partner_trans)
            notes_collection.add_data(notes_trans)
            modality_collection.add_data(modality_trans)
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)
            date_updated_collection.add_data(date_updated_trans)


            # Deduplicate
            treatment_key = (
                therapeutic_area,
                treatment_name,
                indication,
                phase,
                partner,
                notes
            )
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="MacroGenics",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    date_last_changed=date_updated_collection.get_collection_as_json()
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for MacroGenics.")

        # You now have `date_last_updated` and a list of `treatments`.
        # If you need to return the date, you can do so here. 
        # For example: return {"data": treatments, "last_updated": date_last_updated}
        # Or just return the treatments if you only want that from this function.
        
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Macrogenics's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Macrogenics script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []