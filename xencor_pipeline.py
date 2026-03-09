# xencor_pipeline.py

import re
import logging
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these imports to match your project structure:
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # Or keep your own logic for mapping "PHASE 2" etc.
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

###############################################################################
# 1) Fetch function
###############################################################################
async def fetch_xencor_html():
    """
    Fetches the Xencor pipeline page via Zyte.
    """
    try:
        url = "https://xencor.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Xencor HTML: {e}")
        return None

###############################################################################
# 2) Parsing Helper Functions (same logic as your original script)
###############################################################################
def parse_treatment_and_target(h2_tag):
    """
    Attempt to split something like:
        "Vudalimab (PD-1 x CTLA-4)"
    into:
        ("Vudalimab", "PD-1 x CTLA-4")
    If parentheses are not found, just return (text, "")
    """
    text = h2_tag.get_text(strip=True)
    match = re.match(r"^(.*?)\s*\((.*?)\)$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def extract_phase_and_comment(li_text):
    """
    If the text is "PHASE 2  |  +/- standard of care",
    then:
       phase_only = "PHASE 2"
       comment    = "PHASE 2  |  +/- standard of care"
    """
    parts = li_text.split("|", maxsplit=1)
    phase_only = parts[0].strip()
    comment = li_text.strip()
    return phase_only, comment

###############################################################################
# 3) Low-level Parsing: parse_xencor_pipeline
###############################################################################
def parse_xencor_pipeline(html_content):
    """
    Low-level parser that extracts the pipeline data from the raw HTML.
    Returns a list of dictionaries with keys:
       "treatment_name", "target", "domain", "indication", "phase", 
       "comment", "partners", "notes"
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    # locate all <h2> headings that define a new pipeline program
    h2_list = soup.select("div.av-special-heading-h2 h2.av-special-heading-tag")

    all_entries = []

    for h2_tag in h2_list:
        # 1) parse "name" + "target"
        treatment_name, target = parse_treatment_and_target(h2_tag)

        # 2) also grab the <a> link's href
        a_tag = h2_tag.select_one("a.av-heading-link")
        treatment_url = a_tag.get("href", "") if a_tag else ""

        # 3) find "partner" subheading
        heading_wrapper = h2_tag.find_parent("div", class_="av-special-heading-h2")
        if heading_wrapper:
            partner_div = heading_wrapper.select_one("div.av-subheading_below")
        else:
            partner_div = None

        if partner_div:
            partner_text = partner_div.get_text(strip=True)
            partner_list = [p.strip() for p in partner_text.split(",") if p.strip()]
        else:
            partner_list = []

        # 4) find the parent grid
        parent_grid = h2_tag.find_parent("div", class_="av-layout-grid-container")
        if not parent_grid:
            continue

        data_grids = []
        sibling = parent_grid
        while True:
            sibling = sibling.find_next_sibling()
            if not sibling:
                break
            # If we see another heading => new program => stop
            if sibling.select_one("h2.av-special-heading-tag"):
                break
            clz = sibling.get("class", [])
            # Each data grid has these classes
            if "av-layout-grid-container" in clz and "av-border-top-bottom" in clz:
                data_grids.append(sibling)

        # 5) parse the data grids
        current_domain = None

        for grid in data_grids:
            flex_cells = grid.select(".flex_cell.no_margin")

            # group them in sets of 3
            triple_rows = []
            temp = []
            for cell in flex_cells:
                temp.append(cell)
                if len(temp) == 3:
                    triple_rows.append(temp)
                    temp = []

            # 6) parse each triple => domain, indications, phase
            for tri in triple_rows:
                domain_div = tri[0].select_one("h3")
                if domain_div and domain_div.get_text(strip=True):
                    current_domain = domain_div.get_text(strip=True)

                indication_div = tri[1].select_one("h3")
                indication_text = indication_div.get_text(strip=True) if indication_div else ""

                phase_text = None
                comment_text = None
                phase_div = tri[2].select_one("div.ready")
                if phase_div:
                    li_tag = phase_div.select_one("ul.pipelabel li")
                    if li_tag:
                        li_str = li_tag.get_text(strip=True)
                        phase_text, comment_text = extract_phase_and_comment(li_str)

                # Possibly multiple indications => split by comma
                indications = [i.strip() for i in indication_text.split(",") if i.strip()]
                if not indications:
                    indications = [""]  # fallback if none

                for ind in indications:
                    entry = {
                        "treatment_name": treatment_name,
                        "target": target,
                        "domain": current_domain,
                        "indication": ind,
                        "phase": phase_text,
                        "comment": comment_text,
                        "partners": partner_list,  # list
                        "notes": treatment_url
                    }
                    all_entries.append(entry)

    return all_entries

###############################################################################
# 4) Process function: parse + clean + build MasterTable
###############################################################################
async def process_xencor_html(html_content):
    """
    Parses Xencor pipeline data from the given HTML, cleans fields, logs errors,
    and returns a list of MasterTable objects in dictionary form.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Xencor pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Xencor script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_xencor_pipeline(html_content)
        if not raw_data:
            logging.warning("No pipeline entries found in Xencor's HTML.")
            send_sms(
                phone_number="9144334333",
                message="Xencor script found no pipeline data. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for row in raw_data:
            raw_treatment_name = row.get("treatment_name", "")
            raw_target = row.get("target", "")
            raw_domain = row.get("domain", "")
            raw_indication = row.get("indication", "")
            raw_phase = row.get("phase", "")
            raw_comment = row.get("comment", "")
            raw_partners = row.get("partners", [])  # list
            raw_notes = row.get("notes", "")        # URL

            # Convert partner list to a single string (or store as multiline)
            partner_text = ", ".join(raw_partners) if raw_partners else ""

            # Clean text
            treatment_name = clean_text(raw_treatment_name)
            target = clean_text(raw_target)
            domain = clean_text(raw_domain)
            indication = clean_text(raw_indication)
            # If you want to unify phase strings, do: phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)
            comment = clean_text(raw_comment)
            partners = clean_text(partner_text)
            notes = clean_text(raw_notes)

            # Validate fields if necessary
            if not treatment_name and not indication:
                logging.warning("Skipping Xencor entry with missing name and indication.")
                continue

            # identification key
            identification_key = generate_identification_key(
                "Xencor",
                treatment_name,
                indication,
                domain
            )

            # Build multilingual data
            treatment_trans = MultilingualData()
            target_trans = MultilingualData()
            domain_trans = MultilingualData()
            indication_trans = MultilingualData()
            phase_trans = MultilingualData()
            comment_trans = MultilingualData()
            partners_trans = MultilingualData()
            notes_trans = MultilingualData()

            treatment_trans.add_translation("en", treatment_name)
            target_trans.add_translation("en", target)
            domain_trans.add_translation("en", domain)
            indication_trans.add_translation("en", indication)
            phase_trans.add_translation("en", phase)
            comment_trans.add_translation("en", comment)
            partners_trans.add_translation("en", partners)
            notes_trans.add_translation("en", notes)

            # Wrap them in collections
            treatment_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            domain_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            comment_coll = MultilingualDataCollection()
            partners_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            treatment_coll.add_data(treatment_trans)
            target_coll.add_data(target_trans)
            domain_coll.add_data(domain_trans)
            indication_coll.add_data(indication_trans)
            phase_coll.add_data(phase_trans)
            comment_coll.add_data(comment_trans)
            partners_coll.add_data(partners_trans)
            notes_coll.add_data(notes_trans)

            # MasterTable record
            record_key = (
                treatment_name, target, domain, indication, phase, comment, partners, notes
            )
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Xencor",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    # Fields
                    treatment_name=treatment_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),     # custom field
                    domain=domain_coll.get_collection_as_json(),     # custom field
                    indication=indication_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    comment=comment_coll.get_collection_as_json(),   # custom
                    partner=partners_coll.get_collection_as_json(),  # naming match your model
                    notes=notes_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Xencor.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Xencor's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Xencor's script: {e}. Please investigate!"
        )
        return []

