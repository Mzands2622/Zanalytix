# arcus_pipeline.py

import re
import logging
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these to your project's structure:
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # If you want to unify phases, or keep your custom parse_phase_from_line
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

###############################################################################
# 1) Fetch function
###############################################################################
async def fetch_arcus_html():
    """
    Fetches the Arcus pipeline page via Zyte.
    """
    try:
        url = "https://arcusbio.com/our-science/pipeline/"
        html_content = await fetch_with_zyte(url)
        return html_content
    except Exception as e:
        logging.error(f"Error fetching Arcus HTML: {e}")
        return None

###############################################################################
# 2) Low-level Parsing Helpers (slightly reorganized from your original script)
###############################################################################
def parse_partners_and_comments(soup):
    """
    Gather all logos (partner_list) and all textual comments (comment_list) from
    the #collab-section in the Arcus pipeline page.
    """
    partner_list = []
    comment_list = []

    collab_section = soup.select_one("#collab-section")
    if not collab_section:
        return partner_list, comment_list

    cards = collab_section.select(".collaborations__card")
    for card in cards:
        logo_el = card.select_one(".collaborations__card__logo img")
        logo_url = logo_el["src"] if (logo_el and logo_el.has_attr("src")) else ""
        if logo_url:
            partner_list.append(logo_url)

        button_el = card.select_one("a.collaborations__card__button")
        if button_el and button_el.has_attr("data-id"):
            modal_id = "modal-" + button_el["data-id"]
            modal_el = soup.select_one(f"#{modal_id}")
            if modal_el:
                text_el = modal_el.select_one(".pipeline-modal__text p")
                if text_el:
                    comment_list.append(text_el.get_text(strip=True))

    return partner_list, comment_list


def parse_abbreviations_and_footnotes(soup):
    """
    Example of parsing abbreviations from .abbreviations__wrapper and footnotes as well.
    Returns abbreviations_map (dict) and footnotes_list (list).
    """
    abbreviations_map = {}
    footnotes_list = []

    abbr_wrapper = soup.select_one(".abbreviations__wrapper")
    if not abbr_wrapper:
        return abbreviations_map, footnotes_list

    paragraphs = abbr_wrapper.select(".abbreviations__section p")
    if not paragraphs:
        return abbreviations_map, footnotes_list

    # 1) Attempt to parse the first <p> for "key: value;" pairs
    first_p_text = paragraphs[0].get_text(" ", strip=True)
    pairs = first_p_text.split(";")
    for pair in pairs:
        pair = pair.strip().rstrip(".")
        if not pair:
            continue
        if ":" in pair:
            key, val = pair.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key:
                abbreviations_map[key] = val

    # 2) Any subsequent <p> might hold footnotes
    for p in paragraphs[1:]:
        footnotes_list.append(p.get_text(" ", strip=True))

    return abbreviations_map, footnotes_list


def add_abbreviation_notes(pipeline_data, abbreviations_map, footnotes_list):
    """
    For each pipeline entry, search certain fields for abbreviations (molecule, target, indication, regimen).
    If found, add "abbr: expansion" to "notes".
    Optionally attach footnotes if the field text includes an asterisk, etc.
    """
    for entry in pipeline_data:
        # We’ll store these new notes in addition to the existing entry["notes"]
        new_notes = entry.get("notes", [])

        # Check these fields for abbreviations
        fields_to_check = [
            entry.get("molecule", ""),
            entry.get("target", ""),
            entry.get("indication", ""),
            entry.get("regimen", "")
        ]

        # Combine them for substring checks
        combined_text = " ".join(fields_to_check).lower()

        # Abbreviations
        for abbr, expansion in abbreviations_map.items():
            if abbr.lower() in combined_text:
                note_str = f"{abbr}: {expansion}"
                if note_str not in new_notes:
                    new_notes.append(note_str)

        # Example footnotes logic: if there's an asterisk in any field => add all footnotes
        # (Or adapt your own condition.)
        if any("*" in field for field in fields_to_check):
            for ft in footnotes_list:
                if ft not in new_notes:
                    new_notes.append(ft)

        entry["notes"] = new_notes

    return pipeline_data


def parse_phase_from_line(line_div):
    """
    Parse the .phase-row for each .line. 
    Return the most advanced phase found (the last valid phase in .phase).
    """
    phase_row = line_div.select_one(".phase-row")
    if not phase_row:
        return ""

    phases_found = []
    blocks = phase_row.select(".phase")
    for block in blocks:
        child_div = block.select_one("div")  # e.g. <div class="p-1 no-show">
        span_el = block.select_one(".mobile-mol-phase")
        if not child_div or not span_el:
            continue

        phase_text = span_el.get_text(strip=True)
        child_div_classes = child_div.get("class", [])
        # If "no-show" or "empty" => skip
        if "no-show" in child_div_classes or "empty" in child_div_classes:
            continue

        phases_found.append(phase_text)

    # Return the last valid phase if any
    return phases_found[-1] if phases_found else ""


def parse_molecule_based_pipeline(soup, partner_list, comment_list):
    """
    Extract pipeline entries from .ind-columns--molecule sections.
    Each .line.flex-row => one or more pipeline entries:
      - molecule, target, indication, study link, line_of_therapy, regimen, phase
      - partner, comment (taken from parent partner_list/comment_list)
    """
    pipeline_entries = []

    molecule_sections = soup.select("div.ind-columns--molecule")
    for molecule_sec in molecule_sections:
        molecule_el = molecule_sec.select_one(".molecule")
        if not molecule_el:
            continue

        # molecule name
        mol_name_el = molecule_el.select_one("p")
        mol_name = mol_name_el.get_text("\n", strip=True) if mol_name_el else ""

        # target (was called "molecule_description" in your script)
        mol_desc_el = molecule_el.select_one(".molecule-description p")
        target_text = mol_desc_el.get_text(strip=True) if mol_desc_el else ""

        # Each row => .line.flex-row
        line_divs = molecule_sec.select(".lines .line.flex-row")
        for line_div in line_divs:
            # Indication
            indication_el = line_div.select_one(".molecule-indication p")
            indication = indication_el.get_text(strip=True) if indication_el else ""

            # Study link
            link_el = line_div.select_one(".name-link a")
            study_link = link_el["href"].strip() if (link_el and link_el.has_attr("href")) else ""

            # Regimen text (with line_of_therapy on first line)
            regimen_el = line_div.select_one(".regimen .name")
            regimen_text = regimen_el.get_text("\n", strip=True) if regimen_el else ""
            lines_split = regimen_text.split("\n")
            therapy_line = lines_split[0].strip() if lines_split else ""
            regimen_only = "\n".join(ln.strip() for ln in lines_split[1:]).strip()

            # Phase
            phases = parse_phase_from_line(line_div)

            pipeline_entries.append({
                "molecule": mol_name,
                "target": target_text,
                "indication": indication,
                "study": study_link,
                "line_of_therapy": therapy_line,
                "regimen": regimen_only,
                "phase": phases,
                # Repeated partner/comment lists in each entry
                "partner": partner_list,
                "comment": comment_list,
                "notes": []  # We'll populate abbreviations/footnotes next
            })

    return pipeline_entries


def parse_arcus_pipeline_html(html_content):
    """
    End-to-end parsing from raw HTML:
      1) parse partner/comment data
      2) parse abbreviations & footnotes
      3) parse main molecule pipeline
      4) attach abbreviation notes & optional footnotes
    Returns a list of dictionaries with all fields.
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    # 1) Gather partner & comment data
    partner_list, comment_list = parse_partners_and_comments(soup)

    # 2) Parse abbreviations / footnotes
    abbreviations_map, footnotes_list = parse_abbreviations_and_footnotes(soup)

    # 3) Parse the molecule-based pipeline
    pipeline_data = parse_molecule_based_pipeline(soup, partner_list, comment_list)

    # 4) Add abbreviation notes (and footnotes) to pipeline entries
    pipeline_data = add_abbreviation_notes(pipeline_data, abbreviations_map, footnotes_list)

    return pipeline_data

###############################################################################
# 3) Process function: clean, log, build MasterTable
###############################################################################
async def process_arcus_html(html_content):
    """
    Parses Arcus pipeline data, logs errors, cleans fields, and returns MasterTable objects.
    
    We'll choose an identification key of (molecule, indication, line_of_therapy).
    Adapt as you see fit.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Arcus pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Arcus script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_arcus_pipeline_html(html_content)
        if not raw_data:
            logging.warning("No pipeline entries found in Arcus HTML.")
            send_sms(
                phone_number="9144334333",
                message="Arcus script found no pipeline data. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for entry in raw_data:
            raw_molecule = entry.get("molecule", "")
            raw_target = entry.get("target", "")
            raw_indication = entry.get("indication", "")
            raw_study = entry.get("study", "")
            raw_line = entry.get("line_of_therapy", "")
            raw_regimen = entry.get("regimen", "")
            raw_phase = entry.get("phase", "")
            raw_partner_list = entry.get("partner", [])
            raw_comment_list = entry.get("comment", [])
            raw_notes_list = entry.get("notes", [])

            # Convert partner/comment to multiline or comma-separated
            combined_partner = ", ".join(raw_partner_list) if raw_partner_list else ""
            combined_comment = "\n".join(raw_comment_list) if raw_comment_list else ""
            combined_notes = "\n".join(raw_notes_list) if raw_notes_list else ""

            # Clean text
            molecule = clean_text(raw_molecule)
            target = clean_text(raw_target)
            indication = clean_text(raw_indication)
            study = clean_text(raw_study)
            line_of_therapy = clean_text(raw_line)
            regimen = clean_text(raw_regimen)
            # Optionally unify phase with clean_phase
            # phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)
            partner = clean_text(combined_partner)
            comment = clean_text(combined_comment)
            notes = clean_text(combined_notes)

            # Identification Key (molecule, indication, line_of_therapy)
            identification_key = generate_identification_key(
                "Arcus",
                molecule,
                indication,
                regimen
            )

            # Build multilingual fields
            molecule_trans = MultilingualData()
            target_trans = MultilingualData()
            indication_trans = MultilingualData()
            study_trans = MultilingualData()
            line_trans = MultilingualData()
            regimen_trans = MultilingualData()
            phase_trans = MultilingualData()
            partner_trans = MultilingualData()
            comment_trans = MultilingualData()
            notes_trans = MultilingualData()

            molecule_trans.add_translation("en", molecule)
            target_trans.add_translation("en", target)
            indication_trans.add_translation("en", indication)
            study_trans.add_translation("en", study)
            line_trans.add_translation("en", line_of_therapy)
            regimen_trans.add_translation("en", regimen)
            phase_trans.add_translation("en", phase)
            partner_trans.add_translation("en", partner)
            comment_trans.add_translation("en", comment)
            notes_trans.add_translation("en", notes)

            molecule_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            study_coll = MultilingualDataCollection()
            line_coll = MultilingualDataCollection()
            regimen_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            partner_coll = MultilingualDataCollection()
            comment_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            molecule_coll.add_data(molecule_trans)
            target_coll.add_data(target_trans)
            indication_coll.add_data(indication_trans)
            study_coll.add_data(study_trans)
            line_coll.add_data(line_trans)
            regimen_coll.add_data(regimen_trans)
            phase_coll.add_data(phase_trans)
            partner_coll.add_data(partner_trans)
            comment_coll.add_data(comment_trans)
            notes_coll.add_data(notes_trans)

            record_key = (
                molecule, 
                indication, 
                line_of_therapy, 
                regimen, 
                phase, 
                partner, 
                comment, 
                notes
            )
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Arcus Biosciences",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    # Fields
                    molecule=molecule_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    study=study_coll.get_collection_as_json(),
                    line_of_therapy=line_coll.get_collection_as_json(),
                    regimen=regimen_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    partner=partner_coll.get_collection_as_json(),
                    comment=comment_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json(),
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Arcus.")
        return results

    except Exception as e:
        logging.error(f"Error scraping Arcus pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Arcus script error: {e}. Please investigate!"
        )
        return []

