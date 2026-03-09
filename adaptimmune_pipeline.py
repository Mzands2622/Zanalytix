# adaptimmune_pipeline.py

import re
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these imports to match your actual project setup
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # if you want to unify your phase text or keep your custom approach
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)


async def fetch_adaptimmune_html():
    """
    Fetches the Adaptimmune pipeline page via Zyte.
    """
    try:
        url = "https://www.adaptimmune.com/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Adaptimmune HTML: {e}")
        return None


def parse_footnotes(soup):
    """
    Build a map from footnote symbol (e.g. '†') to its text.
    Example: { '†': 'Some footnote explanation', ... }
    """
    footnotes_map = {}
    footnotes_cell = soup.select_one("td.pipeline-footnotes")
    if not footnotes_cell:
        return footnotes_map

    for p_tag in footnotes_cell.select("p"):
        text = p_tag.get_text(strip=True)
        if not text:
            continue

        # If a line begins with a special character (like †), treat that as the symbol.
        match = re.match(r'^([^\w\s]+)', text)
        if match:
            symbol = match.group(1)
            remainder = text[len(symbol):].strip()
            footnotes_map[symbol] = remainder
        else:
            pass

    return footnotes_map


def parse_pipeline_table(table, footnotes_map, base_url):
    """
    Given a <table class="pipeline-table">, parse each row to extract fields:
      treatment_name, target, comment, phase, notes (list).
    """
    rows = table.select("tbody > tr")
    treatments = []
    current_program_raw = None

    for row in rows:
        # Skip if it's a footnotes row
        if row.select_one("td.pipeline-footnotes"):
            continue

        # Program cell
        program_cell = row.find("td", class_="col-program") or \
                       row.find("td", attrs={"data-title": "Program"})
        if program_cell:
            current_program_raw = program_cell.get_text(strip=True)
        if not current_program_raw:
            continue

        # Extract [TARGET] from treatment name
        name_match = re.match(r"^(.*?)\s*\[(.*?)\]\s*$", current_program_raw)
        if name_match:
            treatment_name = name_match.group(1).strip()
            target = name_match.group(2).strip()
        else:
            treatment_name = current_program_raw
            target = ""

        # Comment cell
        comment_cell = row.find("td", class_="col-trial-name") or \
                       row.find("td", attrs={"data-title": "Trial Name(s) / Indications / Design"})
        comment = comment_cell.get_text(strip=True) if comment_cell else ""

        # Determine highest active phase
        phase_cells = row.find_all("td", attrs={"data-phase": True})
        found_phase = "No info"
        for c in reversed(phase_cells):
            span = c.select_one("span.text.sr-only")
            if span:
                phase_text = span.get_text(strip=True)
                if "not started" not in phase_text.lower():
                    found_phase = phase_text
                    break
        # Remove " in progress"
        found_phase = found_phase.replace(" in progress", "")

        # Collect notes (footnotes + last-col content)
        matched_notes = []

        # Footnotes: if the footnote symbol is in this row's text, add the footnote text
        row_text = row.get_text()
        for symbol, note_text in footnotes_map.items():
            if symbol in row_text:
                matched_notes.append(note_text)

        # The last column might have extra text or a link
        all_tds = row.find_all("td")
        if all_tds:
            last_td = all_tds[-1]
            extra_text = last_td.get_text(strip=True)
            if extra_text:
                link_tag = last_td.find("a")
                if link_tag:
                    link_href = link_tag.get("href", "").strip()
                    absolute_url = urljoin(base_url, link_href)
                    matched_notes.append(f"{extra_text} ({absolute_url})")
                else:
                    matched_notes.append(extra_text)

        treatment_data = {
            "treatment_name": treatment_name,
            "target": target,
            "comment": comment,
            "phase": found_phase,
            "notes": matched_notes  # list of strings
        }
        treatments.append(treatment_data)

    return treatments


def parse_adaptimmune_pipeline(html_content):
    """
    Coordinates footnote parsing and pipeline-table parsing.
    Returns a list of raw dictionaries with keys:
       treatment_name, target, comment, phase, notes (list).
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    footnotes_map = parse_footnotes(soup)

    pipeline_tables = soup.find_all("table", class_="pipeline-table")
    if not pipeline_tables:
        print("No pipeline tables found.")
        return []

    base_url = "https://www.adaptimmune.com"
    all_treatments = []
    for table in pipeline_tables:
        treatments_from_this_table = parse_pipeline_table(table, footnotes_map, base_url)
        all_treatments.extend(treatments_from_this_table)

    return all_treatments


async def process_adaptimmune_html(html_content):
    """
    Parses, cleans, logs errors, and builds MasterTable objects for Adaptimmune pipeline data.
    
    Per your request, the identification_key = (treatment_name, target, first word of notes[0] or "N/A").
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Adaptimmune pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Adaptimmune script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_adaptimmune_pipeline(html_content)
        if not raw_data:
            logging.warning("No pipeline entries found in Adaptimmune HTML.")
            send_sms(
                phone_number="9144334333",
                message="Adaptimmune script found no pipeline data. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for row in raw_data:
            raw_treatment_name = row.get("treatment_name", "")
            raw_target = row.get("target", "")
            raw_comment = row.get("comment", "")
            raw_phase = row.get("phase", "")
            notes_list = row.get("notes", [])  # list of strings

            # Convert the notes list to a single multi-line string or keep as is
            notes_combined = "\n".join(notes_list) if notes_list else ""

            # ---------------------------------------------------------
            # 1) Clean each field
            # ---------------------------------------------------------
            treatment_name = clean_text(raw_treatment_name)
            target = clean_text(raw_target)
            comment = clean_text(raw_comment)
            # If you want a standardized Phase approach, do: phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)
            notes = clean_text(notes_combined)

            # ---------------------------------------------------------
            # 2) Build the identification key
            #    - treatment_name
            #    - target
            #    - first word of notes_list[0] or "N/A"
            # ---------------------------------------------------------
            if notes_list:
                # find the first word in the first note
                first_note = notes_list[0].strip()
                words = re.findall(r"\S+", first_note)
                first_word = words[0] if words else "N/A"
            else:
                first_word = "N/A"

            identification_key = generate_identification_key(
                # You might do something like: f"{treatment_name}_{target}_{first_word}"
                # but we'll stay consistent with your multi-part approach:
                "Adaptimmune",
                treatment_name,
                target,
                first_word
            )

            # ---------------------------------------------------------
            # 3) Create multilingual data
            # ---------------------------------------------------------
            treatment_trans = MultilingualData()
            target_trans = MultilingualData()
            comment_trans = MultilingualData()
            phase_trans = MultilingualData()
            notes_trans = MultilingualData()

            treatment_trans.add_translation("en", treatment_name)
            target_trans.add_translation("en", target)
            comment_trans.add_translation("en", comment)
            phase_trans.add_translation("en", phase)
            notes_trans.add_translation("en", notes)

            # Wrap in collections
            treatment_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            comment_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            treatment_coll.add_data(treatment_trans)
            target_coll.add_data(target_trans)
            comment_coll.add_data(comment_trans)
            phase_coll.add_data(phase_trans)
            notes_coll.add_data(notes_trans)

            # ---------------------------------------------------------
            # 4) Build MasterTable record
            # ---------------------------------------------------------
            record_key = (treatment_name, target, comment, phase, notes)
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Adaptimmune",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    treatment_name=treatment_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    comment=comment_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Adaptimmune.")
        return results

    except Exception as e:
        logging.error(f"Error scraping Adaptimmune's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Adaptimmune script: {e}. Please investigate!"
        )
        return []
