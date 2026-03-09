from function_app import (
    fetch_with_zyte,         # Use your project's Zyte fetch function
    clean_phase,             # Optional if you want to normalize phases
    clean_text,              # Optional if you want to clean text consistently
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

def parse_servier_footnotes(soup):
    """
    Look for the <p class="has-small-font-size"> footnotes paragraph, then build
    two dictionaries:

      phase_footnotes_map = { "PCD": "Preclinical development phase", "1": "Phase 1", ... }  # strictly phase
      general_footnotes_map = { "R/R": "Relapsed/Refractory", ... }                          # everything else

    Return (phase_footnotes_map, general_footnotes_map).
    """

    p_candidates = soup.find_all("p", class_="has-small-font-size")
    if not p_candidates:
        logging.info("DEBUG: No <p class='has-small-font-size'> found at all.")
        return {}, {}

    footnotes_p = None
    for ptag in p_candidates:
        text = ptag.get_text(strip=True)
        # Identify the footnotes <p> by looking for "PCD=" or "*Cema-Cel" or "R/R"
        if "PCD=" in text or "*Cema-Cel" in text or "R/R" in text:
            footnotes_p = ptag
            break

    if not footnotes_p:
        logging.info("DEBUG: Found <p class='has-small-font-size'> tags, but none had footnotes text.")
        return {}, {}

    logging.info("DEBUG: Using footnotes paragraph: %r", footnotes_p.get_text(strip=True))

    lines = footnotes_p.get_text(separator="\n").split("\n")

    phase_footnotes_map = {}
    general_footnotes_map = {}

    def parse_pairs(line):
        pairs = []
        for piece in line.split(","):
            piece = piece.strip()
            match = re.match(r"^(\S+)\s*=\s*(.*)$", piece)
            if match:
                key = match.group(1).strip()
                val = match.group(2).strip()
                pairs.append((key, val))
        return pairs

    # -- The first line => phase footnotes (PCD, 1, 2, 3, etc.). 
    #    We'll *exclude* ND from here so it won't override phase.
    if lines:
        first_line_pairs = parse_pairs(lines[0])
        for (key, val) in first_line_pairs:
            # unify 'DCP' -> 'PCD'
            if key.strip().lower() == "dcp":
                key = "PCD"
            # If the key is ND, let's NOT store it in phase_footnotes_map. 
            # We'll handle it as a general footnote instead.
            if key.upper() == "ND":
                continue  
            phase_footnotes_map[key] = val

    # -- Subsequent lines => general footnotes (R/R, *Cema-Cel, etc.)
    for line in lines[1:]:
        pairs = parse_pairs(line)
        if pairs:
            for (key, val) in pairs:
                # If the key starts with '*', unify it to '*'
                if key.startswith("*"):
                    key = "*"
                general_footnotes_map[key] = val
        else:
            if "=" in line:
                continue
            else:
                match = re.match(r"^(\S+)\s+(.*)$", line.strip())
                if match:
                    key = match.group(1)
                    val = match.group(2)
                    # again, unify star keys
                    if key.startswith("*"):
                        key = "*"
                    general_footnotes_map[key] = val
                else:
                    # if the entire line is one token
                    if line.strip().startswith("*"):
                        general_footnotes_map["*"] = ""
                    else:
                        general_footnotes_map[line.strip()] = ""


    # -- Now forcibly add ND => 'Not disclosed' to the general map
    #    so *any* occurrence of ND in text will add "Not disclosed" to notes.
    general_footnotes_map["ND"] = "Not disclosed"

    # -- Also forcibly add "*" => some star footnote text (or reuse the text from line)
    #    so if we see an asterisk anywhere, we add it to notes.
    if "*" not in general_footnotes_map:
        # Add your star footnote text (this can be the text you want appended)
        general_footnotes_map["*"] = "Footnote about the * symbol"

    logging.info("DEBUG: final phase_footnotes_map = %s", phase_footnotes_map)
    logging.info("DEBUG: final general_footnotes_map = %s", general_footnotes_map)
    return phase_footnotes_map, general_footnotes_map


def match_footnotes_in_text(text, footnotes_map):
    """
    Returns a list of all footnote definitions that match any keys 
    found in 'text'.

    We do a special check for "*": if the key == "*" and '*' is in 'text',
    we append that definition.
    Similarly, for any other key, if 'key' in 'text', we append that definition.
    """
    matched = []
    # Guard: if text is empty, just return
    if not text:
        return matched

    for key, definition in footnotes_map.items():
        if key == "*":
            # If there's an asterisk anywhere in text, add the footnote
            if "*" in text:
                matched.append(definition)
        else:
            # Normal substring check
            if key in text:
                matched.append(definition)

    return matched


# ---------------------------------------
# EXTRACT ITEM DATA HELPER
# ---------------------------------------
def extract_servier_item_data(
    item_div,
    major_category=None,
    sub_category=None,
    phase_footnotes_map=None,
    general_footnotes_map=None
):
    data = {
        "major_category": major_category,
        "sub_category": sub_category,
        "compound_or_moa": None,
        "project": None,
        "therapeutic_area": None,
        "phase": None,
        "territory": None,
        "partner": None,
        "notes": [],
    }

    accordion_div = item_div.find("div", class_="accordion flex")
    if accordion_div:
        columns = accordion_div.find_all("div", recursive=False)
        if len(columns) >= 3:
            comp_text = columns[0].get_text(strip=True)
            proj_text = columns[1].get_text(strip=True)
            area_text = columns[2].get_text(strip=True)

            # Collect notes from these fields using 'general_footnotes_map'
            comp_notes = match_footnotes_in_text(comp_text, general_footnotes_map)
            proj_notes = match_footnotes_in_text(proj_text, general_footnotes_map)
            area_notes = match_footnotes_in_text(area_text, general_footnotes_map)

            data["compound_or_moa"] = comp_text
            data["project"] = proj_text
            data["therapeutic_area"] = area_text
            data["notes"].extend(comp_notes + proj_notes + area_notes)

        # Identify final (highest) phase
        phase_div = accordion_div.find("div", class_="phases")
        if phase_div:
            phase_boxes = phase_div.find_all("div", class_="phase")
            valid_phases = []
            for p in phase_boxes:
                style_attr = p.get("style", "").lower().replace(" ", "")
                if "background-color" in style_attr:
                    phase_text = p.get_text(strip=True)
                    if phase_text:
                        valid_phases.append(phase_text)

            if valid_phases:
                raw_phase = valid_phases[-1]
                # Look up raw_phase in phase_footnotes_map
                phase_notes = match_footnotes_in_text(raw_phase, phase_footnotes_map)

                if phase_notes:
                    # e.g. "1" => "Phase 1"
                    data["phase"] = phase_notes[-1]
                else:
                    data["phase"] = raw_phase

                # Because we *only* want ND in notes, we removed ND from phase_footnotes_map
                # If "ND" is in raw_phase, it won't override phase, but 
                # the "ND" => "Not disclosed" entry in general map can still catch 
                # if that appears in a different field. Or if you want ND in notes 
                # even if it's the phase, you can do:
                if "ND" in raw_phase:
                    data["notes"].append("Not disclosed")

    # hidden panel might hold territory/partner
    hidden_panel = item_div.find("div", id=re.compile(r"accordion-panel-"))
    if hidden_panel:
        flex_wrap = hidden_panel.find("div", class_="flex flex-wrap")
        if flex_wrap:
            # territory
            territory_block = flex_wrap.find("div", text="Territory", class_="title")
            if territory_block:
                territory_value_div = territory_block.find_next_sibling("div")
                if territory_value_div:
                    territory_text = territory_value_div.get_text(strip=True)
                    data["territory"] = territory_text
                    territory_notes = match_footnotes_in_text(territory_text, general_footnotes_map)
                    data["notes"].extend(territory_notes)

            # partner
            partner_block = flex_wrap.find("div", text="Partner", class_="title")
            if partner_block:
                partner_value_div = partner_block.find_next_sibling("div")
                if partner_value_div:
                    img_tag = partner_value_div.find("img", alt=True)
                    if img_tag and img_tag['alt'].strip():
                        partner_text = img_tag['alt'].strip()
                    else:
                        partner_text = partner_value_div.get_text(strip=True) or None
                    if partner_text:
                        data["partner"] = partner_text
                        partner_notes = match_footnotes_in_text(partner_text, general_footnotes_map)
                        data["notes"].extend(partner_notes)

    # deduplicate
    data["notes"] = list(set(data["notes"]))
    return data


# ---------------------------------------
# FETCH HTML FUNCTION
# ---------------------------------------
async def fetch_servier_html():
    try:
        url = "https://servier.com/en/research-innovation/our-development-pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Servier pipeline URL: {e}", exc_info=True)
        return None


# ---------------------------------------
# PROCESS HTML FUNCTION
# ---------------------------------------
async def process_servier_html(html_content):
    try:
        if not html_content:
            logging.warning("No HTML content received for Servier pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Servier script returned no HTML content. Please investigate!"
            )
            return []
        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Parse footnotes from the paragraph
        phase_footnotes_map, general_footnotes_map = parse_servier_footnotes(soup)

        raw_records = []

        # 2) Identify <h2 class="wp-block-heading"> blocks
        major_sections = soup.find_all("h2", class_="wp-block-heading")
        for h2 in major_sections:
            major_category = h2.get_text(strip=True)
            section_sibling = h2.find_next_sibling()

            while section_sibling:
                if section_sibling.name == "h2":
                    break

                # <p> with <mark> => sub_category
                if section_sibling.name == "p":
                    mark_tag = section_sibling.find("mark")
                    sub_category = mark_tag.get_text(strip=True) if mark_tag else None

                    pipeline_div = section_sibling.find_next_sibling("div", class_="wp-block-array-pipeline")
                    if pipeline_div:
                        items_container = pipeline_div.find("div", class_="content")
                        if items_container:
                            item_divs = items_container.find_all("div", class_="item", recursive=False)
                            for item_div in item_divs:
                                record = extract_servier_item_data(
                                    item_div,
                                    major_category,
                                    sub_category,
                                    phase_footnotes_map,
                                    general_footnotes_map
                                )
                                raw_records.append(record)

                # Or the pipeline may directly appear
                elif (
                    section_sibling.name == "div"
                    and "wp-block-array-pipeline" in section_sibling.get("class", [])
                ):
                    sub_category = None
                    items_container = section_sibling.find("div", class_="content")
                    if items_container:
                        item_divs = items_container.find_all("div", class_="item", recursive=False)
                        for item_div in item_divs:
                            record = extract_servier_item_data(
                                item_div,
                                major_category,
                                sub_category,
                                phase_footnotes_map,
                                general_footnotes_map
                            )
                            raw_records.append(record)

                section_sibling = section_sibling.find_next_sibling()

        # 3) Deduplicate
        deduped_records = []
        seen_keys = set()
        for rec in raw_records:
            key = (
                rec["major_category"],
                rec["compound_or_moa"],
                rec["project"],
                rec["therapeutic_area"],
                rec["phase"],
                rec["territory"],
                rec["partner"],
            )
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_records.append(rec)

        # 4) Convert to MasterTable-like objects
        treatments = []
        processed_treatments = set()
        for rec in deduped_records:
            try:
                phase = rec["phase"] or ""
                compound_or_moa = rec["compound_or_moa"] or ""
                project = rec["project"] or ""
                therapeutic_area = rec["therapeutic_area"] or ""
                sub_category = rec["sub_category"] or ""
                territory = rec["territory"] or ""
                partner = rec["partner"] or ""
                major_category = rec["major_category"] or ""
                notes_list = rec["notes"] or []

                phase = clean_phase(phase)
                compound_or_moa = clean_text(compound_or_moa)
                project = clean_text(project)
                therapeutic_area = clean_text(therapeutic_area)
                sub_category = clean_text(sub_category)
                territory = clean_text(territory)
                partner = clean_text(partner)
                major_category = clean_text(major_category)
                notes_list = clean_text(notes_list)

                # Convert lists to multilingual data
                notes_list_mld = MultilingualData()
                notes_list_mld.add_translation('en', notes_list)
                notes_list_collection = MultilingualDataCollection()
                notes_list_collection.add_data(notes_list_mld)

                major_category_mld = MultilingualData()
                major_category_mld.add_translation('en', major_category)
                major_category_collection = MultilingualDataCollection()
                major_category_collection.add_data(major_category_mld)

                sub_category_mld = MultilingualData()
                sub_category_mld.add_translation('en', sub_category)
                sub_category_collection = MultilingualDataCollection()
                sub_category_collection.add_data(sub_category_mld)

                compound_mld = MultilingualData()
                compound_mld.add_translation('en', compound_or_moa)
                compound_collection = MultilingualDataCollection()
                compound_collection.add_data(compound_mld)

                project_mld = MultilingualData()
                project_mld.add_translation('en', project)
                project_collection = MultilingualDataCollection()
                project_collection.add_data(project_mld)

                therapy_area_mld = MultilingualData()
                therapy_area_mld.add_translation('en', therapeutic_area)
                therapy_area_collection = MultilingualDataCollection()
                therapy_area_collection.add_data(therapy_area_mld)

                phase_mld = MultilingualData()
                phase_mld.add_translation('en', phase)
                phase_collection = MultilingualDataCollection()
                phase_collection.add_data(phase_mld)

                territory_mld = MultilingualData()
                territory_mld.add_translation('en', territory)
                territory_collection = MultilingualDataCollection()
                territory_collection.add_data(territory_mld)

                partner_mld = MultilingualData()
                partner_mld.add_translation('en', partner)
                partner_collection = MultilingualDataCollection()
                partner_collection.add_data(partner_mld)

                identification_key = generate_identification_key(
                    "Servier",
                    project,
                    therapeutic_area,
                    compound_or_moa
                )
                date_scraped = datetime.now(timezone.utc)

                treatment_key = (
                    compound_or_moa,
                    project,
                    therapeutic_area,
                    phase,
                    major_category,
                    sub_category
                )
                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Servier",
                        therapeutic_area=major_category_collection.get_collection_as_json(),
                        disease_area=sub_category_collection.get_collection_as_json(),
                        treatment_name=compound_collection.get_collection_as_json(),
                        project_type=project_collection.get_collection_as_json(),
                        country=territory_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        partner=partner_collection.get_collection_as_json(),
                        notes=notes_list_collection.get_collection_as_json(),
                        identification_key=identification_key,
                        date_scraped=date_scraped
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(
                    f"Error converting record for {rec['compound_or_moa'] or 'unknown'}: {e}",
                    exc_info=True
                )

        logging.info(f"Processed {len(treatments)} treatments for Servier.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Servier's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Servier script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
