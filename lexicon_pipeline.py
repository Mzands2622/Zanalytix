import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# We assume these come from your function_app or similar module:
from function_app import (
    fetch_with_zyte,       # to fetch HTML
    clean_text,            # cleans generic text
    clean_phase,           # cleans or standardizes the phase text
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# ----------------------------------------------------------
# 1) FETCH HTML Function
# ----------------------------------------------------------
async def fetch_lexicon_html():
    """
    Returns the LexPharma pipeline URL.
    You will later call fetch_with_zyte(url) on this returned value
    to retrieve the actual HTML content.
    """
    try:
        url = "https://www.lexpharma.com/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching LexPharma pipeline URL: {e}")
        return None


# ----------------------------------------------------------
# 2) PROCESS HTML Function
# ----------------------------------------------------------
async def process_lexicon_html(html_content):
    """
    Parses the LexPharma pipeline HTML and returns a list of serialized 
    MasterTable objects (dicts). Each entry has:
      - drug_name
      - indication
      - target
      - phase
      - status
      - notes
    
    We apply `clean_text(...)` to general strings and `clean_phase(...)` to the phase.

    If `html_content` is empty, returns an empty list and possibly sends an SMS alert.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for LexPharma pipeline.")
            send_sms(
                phone_number="9144334333",
                message="LexPharma script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # -----------------------
        # SCRAPING LOGIC
        # -----------------------
        pipeline_items = soup.select("div.css-f4vqvf")

        parsed_results = []
        for item in pipeline_items:
            # 1) Drug name => <div class="css-1xay5mg">...</div>
            drug_el = item.select_one("div.css-1xay5mg")
            drug_name = drug_el.get_text(strip=True) if drug_el else ""
            drug_name = clean_text(drug_name)

            # 2) Indication & target => from <p class="css-1houcn8 e7hxwru1">
            indication = ""
            target = ""

            info_p = item.select_one("p.css-1houcn8.e7hxwru1")
            if info_p:
                # We’ll look for label spans (class="css-16ceglb") to find "Drug candidate / area of study - " or "Target - "
                labels = info_p.select("span.css-16ceglb")
                for lbl in labels:
                    label_text = lbl.get_text(strip=True).lower()
                    # Next text is usually either a text node or in the parent
                    value = ""
                    sib = lbl.next_sibling
                    if sib and sib.name is None:  # text node
                        value = sib.strip()

                    if not value:
                        # Check parent's text after label
                        parent_span = lbl.parent
                        if parent_span:
                            parent_text = parent_span.get_text(separator=" ", strip=True)
                            # e.g. "Drug candidate / area of study - Heart Failure"
                            # or "Target - SGLT2/SGLT1"
                            # remove the label portion
                            cleaned = parent_text.lower().replace(label_text, "", 1).strip()
                            # remove leading "-" if any
                            cleaned = cleaned.lstrip("-").strip()
                            value = cleaned

                    # Now store in the correct field
                    if "drug candidate" in label_text or "area of study" in label_text:
                        indication = clean_text(value)
                    elif "target" in label_text:
                        target = clean_text(value)

            # 3) Phase => from <div class="css-1xtdlhe"><div aria-label="Phase 2">...
            phase = ""
            progress_div = item.select_one("div.css-1xtdlhe")
            if progress_div:
                bar = progress_div.select_one("div[aria-label]")
                if bar:
                    raw_phase = bar.get("aria-label", "").strip()
                    # e.g. "Phase 2", "approved", "Preclinical"
                    # Then pass through your clean_phase
                    phase = clean_phase(raw_phase)

            # 4) Status + Notes => from <p class="css-1vq7wyv e7hxwru1">
            status = ""
            notes = ""
            status_p = item.select_one("p.css-1vq7wyv.e7hxwru1")
            if status_p:
                full_text = status_p.get_text(separator="\n", strip=True)
                lines = full_text.split("\n")
                # The first line likely starts with "Status - "
                if lines:
                    first_line = lines[0].strip()
                    if first_line.lower().startswith("status -"):
                        # remove "status -"
                        remainder = first_line[8:].strip()
                        if remainder:
                            status = remainder
                        if len(lines) > 1:
                            notes = "\n".join(lines[1:]).strip()
                    else:
                        # If first line doesn't have "status -",
                        # treat that entire line as status, next lines as notes
                        status = first_line
                        if len(lines) > 1:
                            notes = "\n".join(lines[1:]).strip()

            # Clean up the final fields
            drug_name = clean_text(drug_name)
            indication = clean_text(indication)
            target = clean_text(target)
            status = clean_text(status)
            notes = clean_text(notes)
            # (phase is already cleaned by clean_phase, but you could do another clean_text(phase) if needed)

            record = {
                "drug_name": drug_name,
                "indication": indication,
                "target": target,
                "phase": phase,
                "status": status,
                "notes": notes
            }
            parsed_results.append(record)

        # ---------------------------------------
        # Convert to MasterTable-based objects
        # ---------------------------------------
        final_results = []
        processed_keys = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in parsed_results:
            drug_name = entry["drug_name"]
            indication = entry["indication"]
            target = entry["target"]
            phase = entry["phase"]
            status = entry["status"]
            notes = entry["notes"]

            # Generate a unique ID
            identification_key = generate_identification_key("LexPharma", drug_name, indication, phase)

            # Build multilingual fields
            drug_trans = MultilingualData()
            drug_trans.add_translation("en", drug_name)

            indic_trans = MultilingualData()
            indic_trans.add_translation("en", indication)

            target_trans = MultilingualData()
            target_trans.add_translation("en", target)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            status_trans = MultilingualData()
            status_trans.add_translation("en", status)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes)

            # Collections
            drug_coll = MultilingualDataCollection()
            drug_coll.add_data(drug_trans)

            indic_coll = MultilingualDataCollection()
            indic_coll.add_data(indic_trans)

            target_coll = MultilingualDataCollection()
            target_coll.add_data(target_trans)

            phase_coll = MultilingualDataCollection()
            phase_coll.add_data(phase_trans)

            status_coll = MultilingualDataCollection()
            status_coll.add_data(status_trans)

            notes_coll = MultilingualDataCollection()
            notes_coll.add_data(notes_trans)

            unique_key = (drug_name, indication, target, phase, status, notes)
            if unique_key not in processed_keys:
                processed_keys.add(unique_key)

                # Build MasterTable object
                master_record = MasterTable(
                    company_name="Lexicon Pharmaceuticals",
                    treatment_name=drug_coll.get_collection_as_json(),
                    indication=indic_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    major_market_status=status_coll.get_collection_as_json(),  # if your MasterTable has 'status' field
                    notes=notes_coll.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )

                final_results.append(master_record.__dict__)

        logging.info(f"Processed {len(final_results)} treatments for LexPharma.")
        return final_results

    except Exception as e:
        logging.error(f"An error occurred scraping LexPharma's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in LexPharma script: {e}. Please investigate!"
        )
        return []
