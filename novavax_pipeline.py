# novavax_pipeline.py

import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these to match your actual project structure:
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # specifically requested for phase
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

async def fetch_novavax_html():
    """
    Fetch the Novavax pipeline page using Zyte.
    """
    try:
        url = "https://www.novavax.com/what-we-do/vaccine-pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Novavax HTML: {e}")
        return None

def parse_footnotes(soup):
    """
    Build a dictionary of footnotes keyed by <sup> number.

    Example footnotes_dict:
      {
         "1": "Authorized in select geographies... [Links: https://example.com]",
         "2": "Commercialized by Serum Institute..."
      }
    """
    footnotes_section = soup.select_one('.mc-pipeline__footnotes .af-text')
    footnotes_dict = {}

    if not footnotes_section:
        return footnotes_dict  # no footnotes found

    paragraphs = footnotes_section.select('p')
    for p in paragraphs:
        sup_el = p.select_one('sup')
        if sup_el:
            note_id = sup_el.get_text(strip=True)  # e.g. "1" or "2" or "3"
            # Remove the <sup> so we can get a clean text
            sup_el.decompose()
            note_text = p.get_text(strip=True)

            # Gather links if any
            links = [a['href'] for a in p.select('a[href]')]
            if links:
                # Append links to the note text
                note_text += f" [Links: {', '.join(links)}]"

            footnotes_dict[note_id] = note_text

    return footnotes_dict

def extract_text_and_notes(element, footnotes_dict):
    """
    Remove <sup> tags from `element`, build a list of any footnotes
    that correspond to those <sup> numbers, then return (clean_text, list_of_footnotes).
    """
    if not element:
        return ("", [])

    local_notes = []
    # Find all <sup> tags
    sup_tags = element.select('sup')
    for sup_tag in sup_tags:
        sup_id = sup_tag.get_text(strip=True)
        # If we have a matching footnote, add its text
        if sup_id in footnotes_dict:
            local_notes.append(footnotes_dict[sup_id])
        # Remove the <sup> tag from the DOM
        sup_tag.decompose()

    clean_content = element.get_text(strip=True)
    return clean_content, local_notes

def parse_novavax_pipeline(html_content):
    """
    Core logic to parse the Novavax pipeline from raw HTML content.
    Returns a list of dictionaries, each representing a pipeline item.
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    # 1) Parse footnotes
    footnotes_dict = parse_footnotes(soup)

    # 2) Locate main pipeline table
    table = soup.select_one('.mc-pipeline__rgnMain table.table')
    if not table:
        print("Could not locate the pipeline table in the HTML.")
        return []

    pipeline_data = []

    # 3) Each product row
    product_rows = table.select('tbody tr.mc-pipeline__rowProduct')

    for row in product_rows:
        row_notes = []

        # -- Therapeutic area & disease
        area_cell = row.select_one('th.mc-pipeline__colTherap')
        if area_cell:
            area_elm = area_cell.select_one('.mc-pipeline__area .af-text')
            therapeutic_area, notes_area = extract_text_and_notes(area_elm, footnotes_dict)
            row_notes.extend(notes_area)

            disease_elm = area_cell.select_one('.mc-pipeline__disease .af-text')
            indication, notes_disease = extract_text_and_notes(disease_elm, footnotes_dict)
            row_notes.extend(notes_disease)
        else:
            therapeutic_area = ""
            indication = ""

        # -- Candidate (treatment name)
        candidate_cell = row.select_one('td.mc-pipeline__colCandidate .mc-pipeline__title .af-text')
        treatment_name, notes_candidate = extract_text_and_notes(candidate_cell, footnotes_dict)
        row_notes.extend(notes_candidate)

        # -- Single phase
        phase_cells = row.select('td.mc-pipeline__colPhase')
        final_phase = None
        for cell in phase_cells:
            label_elm = cell.select_one('.mc-pipeline__phaseLabel .af-text')
            if label_elm:
                label_text, label_notes = extract_text_and_notes(label_elm, footnotes_dict)
                row_notes.extend(label_notes)
                if label_text:
                    final_phase = label_text  # e.g. "Phase 3", "Phase 2b", etc.

        # -- "Authorized" => "Approved"
        authorized_cell = row.select_one('td.mc-pipeline__colCommercial')
        if authorized_cell:
            authorized_label = authorized_cell.select_one('.mc-pipeline__phaseLabel .af-text')
            if authorized_label:
                auth_text, auth_notes = extract_text_and_notes(authorized_label, footnotes_dict)
                row_notes.extend(auth_notes)
                if "Authorized" in auth_text:
                    final_phase = "Approved"

        # -- Partner: images or text fallback
        partner_imgs = []
        partner_cell = row.select_one('td.mc-pipeline__colSponsor')
        if partner_cell:
            imgs = partner_cell.select('img')
            # Collect each image src
            for img_tag in imgs:
                if img_tag.has_attr('src'):
                    partner_imgs.append(img_tag['src'])

            # If no images, fallback to text
            if not partner_imgs:
                text, text_notes = extract_text_and_notes(partner_cell, footnotes_dict)
                row_notes.extend(text_notes)
                if text:
                    partner_imgs.append(text)
        else:
            partner_imgs = []

        # Convert footnotes from list -> single multiline string
        combined_notes = "\n".join(row_notes) if row_notes else ""

        pipeline_data.append({
            "therapeutic_area": therapeutic_area,
            "indication": indication,
            "treatment_name": treatment_name,
            "phase": final_phase,       # We'll "clean_phase" later
            "partner": partner_imgs,    # We'll store as comma- or newline-separated text
            "notes": combined_notes
        })

    return pipeline_data

async def process_novavax_html(html_content):
    """
    Parses Novavax pipeline HTML and returns a list of serialized MasterTable objects.
    Uses clean_phase on the 'phase' specifically, clean_text on other fields.
    """
    from function_app import clean_text  # Already imported at top, but reusing for clarity here

    try:
        if not html_content:
            logging.warning("No HTML content received for Novavax pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Novavax script returned no HTML content. Please investigate!"
            )
            return []

        data_rows = parse_novavax_pipeline(html_content)

        if not data_rows:
            logging.warning("No pipeline entries found in Novavax HTML.")
            send_sms(
                phone_number="9144334333",
                message="Novavax script found no pipeline entries. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for row in data_rows:
            raw_therapeutic_area = row.get("therapeutic_area", "")
            raw_indication = row.get("indication", "")
            raw_treatment_name = row.get("treatment_name", "")
            raw_phase = row.get("phase", "")
            raw_partner_list = row.get("partner", [])
            raw_notes = row.get("notes", "")

            # Convert partner list -> single string
            # (You might choose a different separator: commas, newlines, etc.)
            raw_partner = ", ".join(raw_partner_list) if raw_partner_list else ""

            # ----------------------------------------------------------
            # Clean fields, using clean_phase for phase specifically
            # ----------------------------------------------------------
            therapeutic_area = clean_text(raw_therapeutic_area)
            indication = clean_text(raw_indication)
            treatment_name = clean_text(raw_treatment_name)
            phase = clean_phase(raw_phase)  # As requested, use clean_phase here
            partner = clean_text(raw_partner)
            notes = clean_text(raw_notes)

            # Basic validation
            if not indication and not treatment_name:
                logging.warning("Skipping Novavax entry with missing indication/treatment_name.")
                continue

            # Generate ID key
            identification_key = generate_identification_key(
                "Novavax",
                treatment_name,
                indication,
                therapeutic_area
            )

            # Build multilingual data
            area_trans = MultilingualData()
            indication_trans = MultilingualData()
            treatment_trans = MultilingualData()
            phase_trans = MultilingualData()
            partner_trans = MultilingualData()
            notes_trans = MultilingualData()

            area_trans.add_translation("en", therapeutic_area)
            indication_trans.add_translation("en", indication)
            treatment_trans.add_translation("en", treatment_name)
            phase_trans.add_translation("en", phase)
            partner_trans.add_translation("en", partner)
            notes_trans.add_translation("en", notes)

            area_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            treatment_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            partner_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            area_coll.add_data(area_trans)
            indication_coll.add_data(indication_trans)
            treatment_coll.add_data(treatment_trans)
            phase_coll.add_data(phase_trans)
            partner_coll.add_data(partner_trans)
            notes_coll.add_data(notes_trans)

            record_key = (
                therapeutic_area,
                indication,
                treatment_name,
                phase,
                partner,
                notes
            )
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Novavax",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    therapeutic_area=area_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    treatment_name=treatment_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    partner=partner_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Novavax.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Novavax's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Novavax script: {e}. Please investigate!"
        )
        return []



