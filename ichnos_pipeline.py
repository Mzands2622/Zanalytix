from function_app import (
    fetch_with_zyte,        # your existing helper
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

# -----------------------------------------------------------------
# 1) EXACT SCRAPING LOGIC (unchanged from your “perfect” script)
# -----------------------------------------------------------------
async def fetch_ichnos_html():
    """
    Returns the Ichnos pipeline URL.
    """
    try:
        url = "https://iginnovate.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Ichnos pipeline URL: {e}")
        return None


async def scrape_ichnos_pipeline(url):
    """
    Scrapes the Ichnos pipeline from the given URL, returning a list of row dicts.
    Each dict has these keys:
      {
        "therapeutic_area": str,
        "asset": str,
        "mechanism": str,
        "indication": str,
        "phase": str,
        "trial": str,
        "license_info": dict
      }
    """
    # 1) Fetch the HTML
    html_content = await fetch_with_zyte(url)
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    pipeline_wrappers = soup.select(
        "div.elementor-element.e-con-full.e-flex.e-con.e-parent.e-lazyloaded"
    )

    all_entries = []
    last_therapeutic_area = ""
    current_license_info = None

    # ------------------------------
    # HELPER FUNCTIONS (inline)
    # ------------------------------
    def extract_text(el):
        """Returns text from a BeautifulSoup element."""
        return el.get_text(strip=True) if el else ""

    def parse_license_container(child_blocks):
        """Return a dict with partner name, link, and financials."""
        license_partner = ""
        license_link = ""
        license_financials = ""

        if len(child_blocks) > 1:
            partner_block = child_blocks[1]
            link_a = partner_block.find("a", href=True)
            if link_a:
                license_link = link_a["href"]
            img = partner_block.find("img")
            if img and img.get("alt"):
                license_partner = img["alt"]

        if len(child_blocks) > 2:
            license_financials = extract_text(child_blocks[2])

        return {
            "license_partner_name": license_partner,
            "license_partner_link": license_link,
            "license_financials": license_financials,
        }

    def looks_like_header_row(child_blocks):
        """Decide if this row is obviously a table header row."""
        for block in child_blocks:
            if block.find("th"):
                return True

        text_joined = " ".join(extract_text(cb).lower() for cb in child_blocks)
        potential_header_keywords = ["assets", "description", "indication", "status"]
        if all(k in text_joined for k in potential_header_keywords):
            return True
        return False

    def parse_pipeline_row(child_blocks, therapeutic_area):
        """Parse one pipeline row into our dictionary structure."""
        # If it looks like a header row, skip
        if looks_like_header_row(child_blocks):
            return None

        asset_name = extract_text(child_blocks[0]) if len(child_blocks) > 0 else ""
        mechanism = extract_text(child_blocks[1]) if len(child_blocks) > 1 else ""
        indication = extract_text(child_blocks[2]) if len(child_blocks) > 2 else ""
        phase = extract_text(child_blocks[-1]) if child_blocks else ""

        # Trial extraction
        trial_num = ""
        for cb in child_blocks:
            span = cb.find("span", class_="progress_bar-title")
            if span:
                candidate = span.get_text(strip=True)
                # If it matches NCT\d{8}, keep that. Otherwise keep as-is.
                match = re.search(r"NCT\d{8}", candidate)
                if match:
                    trial_num = match.group(0)
                else:
                    trial_num = candidate
                break

        # skip if no asset name
        if not asset_name or len(asset_name) < 2:
            return None

        return {
            "therapeutic_area": therapeutic_area.strip(),
            "asset": asset_name.strip(),
            "mechanism": mechanism.strip(),
            "indication": indication.strip(),
            "phase": phase.strip(),
            "trial": trial_num,
            "license_info": {}
        }

    def should_skip_entry(entry):
        """Filters out placeholders (like 'pipeline', 'productdescription', etc.)."""
        ta_lower = entry["therapeutic_area"].lower()
        asset_lower = entry["asset"].replace(" ", "").lower()

        if "pipeline" in ta_lower:
            return True
        if "productdescription" in asset_lower:
            return True
        if "ourpipelineiscomprised" in asset_lower:
            return True

        return False

    def post_process_entry(entry):
        """
        Final touches:
         - 'TelazorlimabISB...' => 'Telazorlimab'
         - If 'Partnering-Ready Assets...' => remove license_info
         - Also handle "Diversity" => "Oncology" if you want it
        """
        asset_norm = entry["asset"].lower().replace(" ", "")
        if "telazorlimabisb" in asset_norm:
            entry["asset"] = "Telazorlimab"

        if entry["therapeutic_area"] == "Partnering-Ready Assets to Accelerate Short-Term Value Creation":
            entry["license_info"] = {}

        if "diversity" in entry["therapeutic_area"].lower():
            entry["therapeutic_area"] = "Oncology"

        return entry

    # ---------------------------
    # MAIN LOOP
    # ---------------------------
    for wrapper in pipeline_wrappers:
        h2_tag = wrapper.find(
            "h2", class_="elementor-heading-title elementor-size-default"
        )
        if h2_tag:
            last_therapeutic_area = extract_text(h2_tag)
            continue

        child_blocks = wrapper.select(
            ":scope > div.elementor-element.e-con-full.e-flex.e-con.e-child"
        )
        if not child_blocks:
            continue

        first_block_text = extract_text(child_blocks[0]).lower()

        if "licensed to" in first_block_text:
            current_license_info = parse_license_container(child_blocks)
            continue

        entry = parse_pipeline_row(child_blocks, last_therapeutic_area)
        if not entry:
            continue

        # If we have a license from a previous "Licensed to" block, attach it
        if current_license_info:
            entry["license_info"] = current_license_info.copy()

        # Filter out placeholders
        if should_skip_entry(entry):
            continue

        # Final renames / cleans
        entry = post_process_entry(entry)

        all_entries.append(entry)

    return all_entries


# -----------------------------------------------------------------
# 2) PROCESS + MAP INTO MasterTable (with optional star-note)
# -----------------------------------------------------------------
async def process_ichnos_html(html_content):
    """
    Parses Ichnos' pipeline HTML and returns a list of serialized MasterTable objects.
    We map:
       therapeutic_area -> 'therapeutic_area'
       asset            -> 'treatment_name'
       mechanism        -> 'target'
       indication       -> 'indication'
       phase            -> 'phase'
       trial            -> 'study'
       license_info     -> 'partner'

    Also:
       - If an asterisk '*' is found in asset, mechanism, indication, or phase,
         we look up the text from .elementor-element-ba352d1 and store it in 'notes'.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Ichnos pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Ichnos script returned no HTML content. Please investigate!"
            )
            return []
        soup = BeautifulSoup(html_content, "html.parser")

        # 1) Grab the star note text (if any) from the special div
        star_note_text = ""
        star_note_div = soup.select_one("div.elementor-element-ba352d1.elementor-widget-text-editor")
        if star_note_div:
            star_note_text = star_note_div.get_text(strip=True)

        # 2) We'll replicate the "scrape_ichnos_pipeline" logic locally (no second fetch):
        pipeline_entries = []

        # The function above expects a URL, but we have raw HTML.
        # Let's do: we call the same parsing logic from the code above, but inline.

        # Instead of rewriting everything, let's do:
        # 'scrape_ichnos_pipeline' can't take raw HTML easily, so we'll just
        # replicate the final line that yields 'all_entries':

        # Replicate the same selectors & logic:
        pipeline_wrappers = soup.select(
            "div.elementor-element.e-con-full.e-flex.e-con.e-parent.e-lazyloaded"
        )

        all_entries = []
        last_therapeutic_area = ""
        current_license_info = None

        def extract_text(el):
            return el.get_text(strip=True) if el else ""

        def parse_license_container(child_blocks):
            license_partner = ""
            license_link = ""
            license_financials = ""
            if len(child_blocks) > 1:
                partner_block = child_blocks[1]
                link_a = partner_block.find("a", href=True)
                if link_a:
                    license_link = link_a["href"]
                img = partner_block.find("img")
                if img and img.get("alt"):
                    license_partner = img["alt"]
            if len(child_blocks) > 2:
                license_financials = extract_text(child_blocks[2])
            return {
                "license_partner_name": license_partner,
                "license_partner_link": license_link,
                "license_financials": license_financials,
            }

        def looks_like_header_row(child_blocks):
            for block in child_blocks:
                if block.find("th"):
                    return True
            text_joined = " ".join(extract_text(cb).lower() for cb in child_blocks)
            potential_header_keywords = ["assets", "description", "indication", "status"]
            if all(k in text_joined for k in potential_header_keywords):
                return True
            return False

        def parse_pipeline_row(child_blocks, therapeutic_area):
            if looks_like_header_row(child_blocks):
                return None
            asset_name = extract_text(child_blocks[0]) if len(child_blocks) > 0 else ""
            mechanism = extract_text(child_blocks[1]) if len(child_blocks) > 1 else ""
            indication = extract_text(child_blocks[2]) if len(child_blocks) > 2 else ""
            phase = extract_text(child_blocks[-1]) if child_blocks else ""

            trial_num = ""
            for cb in child_blocks:
                span = cb.find("span", class_="progress_bar-title")
                if span:
                    candidate = span.get_text(strip=True)
                    match = re.search(r"NCT\d{8}", candidate)
                    if match:
                        trial_num = match.group(0)
                    else:
                        trial_num = candidate
                    break

            if not asset_name or len(asset_name) < 2:
                return None

            return {
                "therapeutic_area": therapeutic_area.strip(),
                "asset": asset_name.strip(),
                "mechanism": mechanism.strip(),
                "indication": indication.strip(),
                "phase": phase.strip(),
                "trial": trial_num,
                "license_info": {}
            }

        def should_skip_entry(entry):
            ta_lower = entry["therapeutic_area"].lower()
            asset_lower = entry["asset"].replace(" ", "").lower()
            if "pipeline" in ta_lower:
                return True
            if "productdescription" in asset_lower:
                return True
            if "ourpipelineiscomprised" in asset_lower:
                return True
            return False

        def post_process_entry(entry):
            asset_norm = entry["asset"].lower().replace(" ", "")
            if "telazorlimabisb" in asset_norm:
                entry["asset"] = "Telazorlimab"
            if entry["therapeutic_area"] == "Partnering-Ready Assets to Accelerate Short-Term Value Creation":
                entry["license_info"] = {}
            if "diversity" in entry["therapeutic_area"].lower():
                entry["therapeutic_area"] = "Oncology"
            return entry

        for wrapper in pipeline_wrappers:
            h2_tag = wrapper.find(
                "h2", class_="elementor-heading-title elementor-size-default"
            )
            if h2_tag:
                last_therapeutic_area = extract_text(h2_tag)
                continue

            child_blocks = wrapper.select(
                ":scope > div.elementor-element.e-con-full.e-flex.e-con.e-child"
            )
            if not child_blocks:
                continue

            first_block_text = extract_text(child_blocks[0]).lower()
            if "licensed to" in first_block_text:
                current_license_info = parse_license_container(child_blocks)
                continue

            entry = parse_pipeline_row(child_blocks, last_therapeutic_area)
            if not entry:
                continue

            if current_license_info:
                entry["license_info"] = current_license_info.copy()

            if should_skip_entry(entry):
                continue

            entry = post_process_entry(entry)
            all_entries.append(entry)

        # 'all_entries' now has the standard row dicts
        # each row has {therapeutic_area, asset, mechanism, indication, phase, trial, license_info}
        # ----------------------------------------------------------

        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for row in all_entries:
            # Map them to your final naming:
            therapeutic_area = clean_text(row.get("therapeutic_area", ""))
            treatment_name = clean_text(row.get("asset", ""))
            target = clean_text(row.get("mechanism", ""))
            indication = clean_text(row.get("indication", ""))
            phase = clean_phase(row.get("phase", ""))
            study = clean_text(row.get("trial", ""))
            partner = row.get("license_info", {})

            # ------------------------------------------------------
            # 3) If we see an asterisk in ANY of these fields,
            #    we attach star_note_text to 'notes'.
            # ------------------------------------------------------
            # You can decide which fields to check for '*'.
            # We'll check asset, mechanism, indication, or phase.
            has_asterisk = any(
                ("*" in val) for val in [treatment_name, target, indication, phase]
            )

            # Create a multilingual data for 'notes'
            notes_trans = MultilingualData()
            if has_asterisk and star_note_text:
                # e.g. "*A US IND for rheumatoid arthritis and other autoimmune indications is active."
                notes_trans.add_translation("en", star_note_text)
            else:
                # If no star, store empty or skip adding
                notes_trans.add_translation("en", "")

            notes_collection = MultilingualDataCollection()
            notes_collection.add_data(notes_trans)

            # Build your multilingual fields:
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            target_trans = MultilingualData()
            target_trans.add_translation("en", target)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            study_trans = MultilingualData()
            study_trans.add_translation("en", study)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", str(partner))

            name_trans = MultilingualData()
            name_trans.add_translation("en", treatment_name)

            area_collection = MultilingualDataCollection()
            target_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            target_collection.add_data(target_trans)
            indication_collection.add_data(indication_trans)
            phase_collection.add_data(phase_trans)
            study_collection.add_data(study_trans)
            partner_collection.add_data(partner_trans)
            name_collection.add_data(name_trans)

            # Identification key
            identification_key = generate_identification_key(
                "Ichnos", treatment_name, therapeutic_area, indication, target
            )

            # Build MasterTable
            # (We feed "target" in 'target' field, "treatment_name" in 'treatment_name', etc.)
            master_record = MasterTable(
                company_name="Ichnos Glenmark Innovation",
                treatment_name=name_collection.get_collection_as_json(),
                indication=indication_collection.get_collection_as_json(),
                therapeutic_area=area_collection.get_collection_as_json(),
                phase=phase_collection.get_collection_as_json(),
                target=target_collection.get_collection_as_json(),
                date_scraped=date_scraped,
                identification_key=identification_key,
                study=study_collection.get_collection_as_json(),
                partner=partner_collection.get_collection_as_json(),
                notes=notes_collection.get_collection_as_json(),  # <-- star note goes here
            )

            # Avoid duplicates
            treatment_key = (therapeutic_area, treatment_name, target, indication, phase, study)
            if treatment_key not in processed_treatments:
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Ichnos.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Ichnos's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Ichnos script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []