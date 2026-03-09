# menarini_pipeline.py

import re
import logging
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime, timezone

# Adjust these imports to match your project structure:
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


def _parse_legend_block(legend_block):
    """
    Helper to parse a single <div class="legenda-pipeline"> block
    and return {abbreviation -> explanation}.
    """
    legends_dict = {}
    label_divs = legend_block.select(".labelPipline")
    for item in label_divs:
        strong_el = item.select_one("strong")
        if not strong_el:
            continue

        abbr_text = strong_el.get_text(strip=True).rstrip(":")
        full_text = item.get_text(separator=" ", strip=True)
        remainder = full_text.replace(strong_el.get_text(strip=True), "", 1).strip(": ").strip()
        legends_dict[abbr_text] = remainder
    return legends_dict


def parse_legend_blocks(soup):
    """
    Scrape two blocks of legends separately:
      1) Indication/Mechanism legends (e.g. "ABSSSI" => "Acute Bacterial...")
      2) Phase legends (e.g. "P" => "Preclinical", "I" => "Phase I", etc.)

    Returns (indication_legend_dict, phase_legend_dict).
    """
    all_legenda_blocks = soup.select(".legenda-pipeline")
    indication_legend_dict = {}
    phase_legend_dict = {}

    if len(all_legenda_blocks) >= 1:
        indication_legend_dict = _parse_legend_block(all_legenda_blocks[0])
    if len(all_legenda_blocks) >= 2:
        phase_legend_dict = _parse_legend_block(all_legenda_blocks[1])

    return indication_legend_dict, phase_legend_dict


def _extract_text_including_links(tag):
    """
    Convert a BeautifulSoup Tag into text, but for <a> tags we include '(URL)'.
    Example: <p>See <a href="http://example.com">here</a>.</p> => "See here (http://example.com)."
    """
    for a in tag.select("a"):
        link_text = a.get_text(strip=True)
        link_href = a.get("href", "")
        if link_text and link_href:
            a.string = f"{link_text} ({link_href})"
    return tag.get_text(separator=" ", strip=True)


def parse_modals_with_links(soup):
    """
    Extract each .modal-body as a list of strings, preserving anchor links as 'text (URL)'.
    Returns { modal_id: [list_of_strings], ... }
    """
    modal_dict = {}
    modals = soup.select(".modal.fade")
    for m in modals:
        modal_id = m.get("id")
        if not modal_id:
            continue

        body = m.select_one(".modal-body")
        if not body:
            continue

        element_texts = []
        for child in body.children:
            if isinstance(child, NavigableString):
                text_snip = str(child).strip()
                if text_snip:
                    element_texts.append(text_snip)
            elif isinstance(child, Tag):
                text_w_links = _extract_text_including_links(child)
                if text_w_links.strip():
                    element_texts.append(text_w_links.strip())

        modal_dict[modal_id] = element_texts
    return modal_dict


def parse_menarini_pipeline_html(html_content):
    """
    Low-level function to parse the Menarini pipeline from raw HTML content.
    Returns a list of dicts containing pipeline data with specific targeting of
    Oncology and Anti-infectives tables.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # 1) Parse legends
    indication_legend, phase_legend = parse_legend_blocks(soup)
    # 2) Parse modal-based notes
    modals_data = parse_modals_with_links(soup)

    all_entries = []
    partner_memory = {}  # If partner is missing, use previous for same treatment

    # Define target table IDs
    target_tables = [
        "#dnn_ctr24113_View_CompoundDiv",
        "#dnn_ctr24192_View_CompoundDiv"
    ]

    # Process each target table
    for table_id in target_tables:
        pipeline_div = soup.select_one(table_id)
        if not pipeline_div:
            logging.warning(f"Could not find table {table_id}")
            continue
            
        # Find the nearest preceding h3 with class "galleryTitleH3"
        heading = pipeline_div.find_previous("h3", class_="galleryTitleH3")
        therapeutic_area = heading.get_text(strip=True) if heading else ""

        rows = pipeline_div.select(".table_row")
        for row in rows:
            first_col = row.select_one(".col.first")
            if not first_col:
                continue

            # -- treatment_name
            treatment_name_el = first_col.select_one(".title")  # Changed from span.title
            treatment_name = treatment_name_el.get_text(strip=True) if treatment_name_el else None

            # -- partner(s)
            partner_els = first_col.select(".text")  # Changed from span.text
            partners = [p.get_text(strip=True) for p in partner_els if p.get_text(strip=True)]
            if not partners and treatment_name in partner_memory:
                partners = partner_memory[treatment_name]
            else:
                partner_memory[treatment_name] = partners

            # -- target
            second_col = row.select_one(".col.second")
            target_el = second_col.select_one(".internal-title") if second_col else None
            target = target_el.get_text(strip=True) if target_el else ""

            # -- indication
            third_col = row.select_one(".col.third")
            indication_el = third_col.select_one(".internal-title") if third_col else None
            indication = indication_el.get_text(strip=True) if indication_el else ""

            # -- phase
            fourth_col = row.select_one(".col.fourth")
            if fourth_col:
                phase_cols = fourth_col.select(".pipeline_header .pipeline_col.active")
                if phase_cols:
                    raw_phase = phase_cols[-1].get_text(strip=True)
                    phase = phase_legend.get(raw_phase, raw_phase)
                else:
                    phase = "Unknown"
            else:
                phase = "Unknown"
                
            # Expand if found in legend
            phase = phase_legend.get(phase, phase)

            # -- notes from modals
            notes_list = []
            fifth_col = row.select_one(".col.fifth")
            if fifth_col:
                link = fifth_col.select_one("a.readMore")
                if link and link.has_attr("data-target"):
                    modal_id = link["data-target"].lstrip("#")
                    notes_list = modals_data.get(modal_id, [])

            # If there's no treatment_name, skip
            if not treatment_name:
                continue

            # -- comment (expanded from indication_legend)
            row_text = f"{treatment_name} {' '.join(partners)} {target} {indication}"
            notes_combined = " ".join(notes_list)
            combined_text = f"{row_text} {notes_combined}"
            comment_list = []

            for abbr, explanation in indication_legend.items():
                pattern = rf"\b{re.escape(abbr)}\b"
                if re.search(pattern, combined_text):
                    comment_list.append(f"{abbr}: {explanation}")

            entry_data = {
                "treatment_name": treatment_name,
                "partner": partners,  # list
                "target": target,
                "indication": indication,
                "phase": phase,
                "notes": notes_list,
                "comment": comment_list,
                "therapeutic_area": therapeutic_area  # Using dynamically detected therapeutic area
            }
            all_entries.append(entry_data)

    return all_entries


async def fetch_menarini_html():
    """
    Fetches the Menarini pipeline page via Zyte.
    """
    try:
        url = "https://www.menarini.com/en-us/innovation-research/our-pipeline-and-products"
        return url
    except Exception as e:
        logging.error(f"Error fetching Menarini HTML: {e}")
        return None


async def process_menarini_html(html_content):
    """
    Processes the Menarini pipeline HTML into a list of MasterTable dicts.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Menarini pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Menarini script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_menarini_pipeline_html(html_content)
        if not raw_data:
            logging.warning("No pipeline rows found in Menarini's HTML.")
            send_sms(
                phone_number="9144334333",
                message="Menarini script found no pipeline rows. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for row in raw_data:
            raw_treatment_name = row.get("treatment_name", "")
            raw_partners = row.get("partner", [])  # list
            raw_target = row.get("target", "")
            raw_indication = row.get("indication", "")
            raw_phase = row.get("phase", "")
            notes_list = row.get("notes", [])      # list of strings
            comment_list = row.get("comment", [])  # list of strings
            raw_therapeutic_area = row.get("therapeutic_area", )

            # Join the partners list into a single string
            joined_partners = ", ".join(raw_partners) if raw_partners else ""
            # Join notes into multiline string
            joined_notes = "\n".join(notes_list) if notes_list else ""
            # Join comments as multiline
            joined_comment = "\n".join(comment_list) if comment_list else ""

            # -----------------------------------
            # 1) Clean text fields
            # -----------------------------------
            treatment_name = clean_text(raw_treatment_name)
            partner_str = clean_text(joined_partners)
            target = clean_text(raw_target)
            indication = clean_text(raw_indication)
            phase = clean_phase(raw_phase)
            notes = clean_text(joined_notes)
            comment = clean_text(joined_comment)
            therapeutic_area = clean_text(raw_therapeutic_area)

            # Basic validation (if needed)
            if not treatment_name and not indication:
                logging.warning("Skipping Menarini entry with no treatment_name/indication.")
                continue

            

            # Get note for the identification key
            note_identifier = ""
            if notes_list:  # Use notes_list directly from row.get("notes", [])
                # First check all notes for any link
                found_link = False
                for note in notes_list:
                    link_match = re.search(r'\((http[^)]+)\)', str(note))  # Ensure note is string
                    if link_match:
                        note_identifier = str(link_match.group(1)).strip()  # Convert URL to string and clean
                        found_link = True
                        break
                
                # If no link found anywhere in notes, use first word of first note
                if not found_link:
                    first_note = str(notes_list[0])  # Convert to string
                    note_identifier = str(first_note.split()[0]).strip() if first_note.split() else ""
                
                note_identifier = clean_text(note_identifier)

            # Generate identification key
            identification_key = generate_identification_key(
                "Menarini Group",
                treatment_name,
                indication,
                note_identifier  # Use our new note-based identifier instead of target
            )


            # Build multilingual data
            treatment_trans = MultilingualData()
            partner_trans = MultilingualData()
            target_trans = MultilingualData()
            indication_trans = MultilingualData()
            phase_trans = MultilingualData()
            notes_trans = MultilingualData()
            comment_trans = MultilingualData()
            therapeutic_area_trans = MultilingualData()


            treatment_trans.add_translation("en", treatment_name)
            partner_trans.add_translation("en", partner_str)
            target_trans.add_translation("en", target)
            indication_trans.add_translation("en", indication)
            phase_trans.add_translation("en", phase)
            notes_trans.add_translation("en", notes)
            comment_trans.add_translation("en", comment)
            therapeutic_area_trans.add_translation("en", therapeutic_area)


            treatment_coll = MultilingualDataCollection()
            partner_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()
            comment_coll = MultilingualDataCollection()
            therapeutic_area_coll = MultilingualDataCollection()

            treatment_coll.add_data(treatment_trans)
            partner_coll.add_data(partner_trans)
            target_coll.add_data(target_trans)
            indication_coll.add_data(indication_trans)
            phase_coll.add_data(phase_trans)
            notes_coll.add_data(notes_trans)
            comment_coll.add_data(comment_trans)
            therapeutic_area_coll.add_data(therapeutic_area_trans)

            record_key = (treatment_name, partner_str, target, indication, phase, notes, comment)
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Menarini",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    # Multilingual fields
                    treatment_name=treatment_coll.get_collection_as_json(),
                    partner=partner_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json(),
                    comment=comment_coll.get_collection_as_json(),
                    therapeutic_area=therapeutic_area_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Menarini.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Menarini's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Menarini's script: {e}. Please investigate!"
        )
        return []