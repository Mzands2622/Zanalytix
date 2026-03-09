import logging
import re
import json
from datetime import datetime, timezone
import requests

# Assuming these are imported from your `function_app` or similar:
from function_app import (
    fetch_with_zyte,           # <--- your Zyte-based fetch function
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# -------------------------------------------
# 1) Define a set of valid country codes
# -------------------------------------------
VALID_COUNTRY_CODES = {"US", "EU", "JP", "CN"}

# -------------------------------------------
# 2) Helper function to extract country codes
# -------------------------------------------
def extract_country_codes(indication: str, valid_codes=None):
    """
    Extract recognized country codes inside parentheses from the indication string.
    
    If a pair of parentheses has multiple codes (e.g., '(EU, JP, CN)') we parse each
    code individually and only remove them if *all* are valid. Otherwise, we leave
    that entire set of parentheses intact.

    Returns:
        (cleaned_indication, [list_of_extracted_codes])
    """
    if not valid_codes:
        valid_codes = set()
    
    # Regex: match anything in parentheses
    pattern = r"\(([^)]+)\)"

    recognized_countries = []
    cleaned_indication   = indication

    # Find all parenthetical groups
    matches = re.findall(pattern, indication)
    for match_text in matches:
        # Example: match_text might be "EU, JP, CN" or "US" or "IsKia"
        
        # Split on commas to handle multiple countries in one set of parentheses
        tokens = [t.strip().upper() for t in match_text.split(",")]
        
        # Check if *all* tokens are recognized country codes
        if all(token in valid_codes for token in tokens):
            # If yes, remove the entire "(...)" from the cleaned string
            # Because the entire group is recognized as countries
            sub_pattern = r"\(" + re.escape(match_text) + r"\)"
            cleaned_indication = re.sub(sub_pattern, "", cleaned_indication, 1)
            recognized_countries.extend(tokens)  # store them all
        else:
            # Otherwise, ignore it, because it's something else (e.g. (IMROZ))
            pass

    # Cleanup any extra spaces
    cleaned_indication = cleaned_indication.strip()
    cleaned_indication = re.sub(r"\s{2,}", " ", cleaned_indication)

    return cleaned_indication, recognized_countries

# -------------------------------------------
# 3) Fetch HTML via Zyte (Asynchronous)
# -------------------------------------------
async def fetch_sanofi_french_html():
    """
    Uses your existing 'fetch_with_zyte' function to retrieve
    the fully-rendered HTML for Sanofi’s pipeline page.
    
    Returns the HTML as a string or None on error.
    """
    try:
        url = "https://www.sanofi.com/fr/notre-science/notre-portefeuille"
        return url
    except Exception as e:
        logging.error(f"Error fetching Sanofi pipeline HTML with Zyte: {e}", exc_info=True)
        return None


# -------------------------------------------
# 4) Process HTML into MasterTable records
# -------------------------------------------
async def process_sanofi_french_html(html_content):
    """
    1. Locates the 'projectsList' JSON block via regex
    2. Parses it as JSON
    3. Deduplicates
    4. Builds and returns a list of MasterTable objects (serialized as dict)
       that includes collaboration, notes, submission, etc.
    """
    try:
        # Safety check
        if not html_content:
            logging.warning("No HTML content received for Sanofi pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Sanofi script returned no HTML content. Please investigate!"
            )
            return []

        response = requests.get("https://www.sanofi.com/fr/notre-science/notre-portefeuille")
        response.raise_for_status()
        html_content = response.text  # We store the raw HTML

        date_last_updated = "N/A"

        # Regex to find something like:  
        #   "top": [ { "cmsComponentType": "hero-banner", "title": "...", "text": "Updated on ..." } ]
        pattern_top = r'"top"\s*:\s*\[\s*\{.*?\}\s*\]'
        match_top = re.search(pattern_top, html_content, flags=re.DOTALL)
        if match_top:
            top_str = match_top.group(0)  # e.g. '"top": [{...}]'
            # Extract just the JSON array portion
            start_idx = top_str.find('[')
            end_idx   = top_str.rfind(']')
            top_array_str = top_str[start_idx : end_idx + 1]

            try:
                top_data = json.loads(top_array_str)
                if top_data and isinstance(top_data, list):
                    # top_data[0] might have "text": "Updated on October 25 2024."
                    first_item = top_data[0]
                    if "text" in first_item:
                        date_last_updated = first_item["text"]
            except json.JSONDecodeError as e:
                logging.info("Date last updated text not found!")

            date_last_updated = clean_text(date_last_updated)
                
        # -----------------------------------------------------------
        # (A) Extract the 'projectsList' array from the raw HTML
        # -----------------------------------------------------------
        pattern = r'"projectsList"\s*:\s*\[\s*\{.*?\}\s*\]'
        match = re.search(pattern, html_content, flags=re.DOTALL)
        if not match:
            logging.error("Could not find 'projectsList' JSON chunk in HTML.")
            return []

        projects_list_str = match.group(0)  # e.g. '"projectsList":[{...}]'
        
        # Extract just the JSON array portion
        start_index = projects_list_str.find('[')
        end_index   = projects_list_str.rfind(']')
        json_array_str = projects_list_str[start_index : end_index + 1]

        # -----------------------------------------------------------
        # (B) Parse the array as JSON
        # -----------------------------------------------------------
        try:
            projects = json.loads(json_array_str)
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing 'projectsList' JSON: {e}")
            return []

        # -----------------------------------------------------------
        # (C) Deduplicate
        # -----------------------------------------------------------
        key_fields = [
            "projectName", "therapeuticArea", "phaseLabel", 
            "phaseName", "indication", "description", 
            "collaboration", "notes", "submission"
        ]
        seen_keys       = set()
        deduped_projects = []

        for proj in projects:
            # Build a tuple of lowercase/trimmed fields for dedup
            key = tuple(str(proj.get(f, "")).lower().strip() for f in key_fields)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_projects.append(proj)

        # -----------------------------------------------------------
        # (D) Convert each project to a MasterTable record
        # -----------------------------------------------------------
        date_scraped = datetime.now(timezone.utc)
        master_table_list = []

        for proj in deduped_projects:
            try:
                # 1) Pull out raw fields
                raw_name         = proj.get("projectName", "")
                raw_collab       = proj.get("collaboration", "")
                raw_notes        = proj.get("notes", "")
                raw_submission   = proj.get("submission", "")
                raw_phase_label  = proj.get("phaseLabel", "")
                raw_phase_name   = proj.get("phaseName", "")
                raw_indication   = proj.get("indication", "")
                raw_description  = proj.get("shortDescription", "")
                raw_ther_area    = proj.get("therapeuticArea", "")
                raw_status       = proj.get("status", "")

                # 2) Clean them (text and phase)
                name_str          = clean_text(raw_name)
                collab_str        = clean_text(raw_collab)
                notes_str         = clean_text(raw_notes)
                submission_str    = clean_text(raw_submission)

                # If phaseLabel is empty, fallback to phaseName
                combined_phase    = raw_phase_label or raw_phase_name
                phase_str         = clean_phase(combined_phase)

                # Indication & description
                indication_str    = clean_text(raw_indication)
                description_str   = clean_text(raw_description)

                # Therapeutic area, status
                therapeutic_area  = clean_text(raw_ther_area)
                status            = clean_text(raw_status)

                # 3) Extract recognized country codes from the indication
                cleaned_indication_str, country_list = extract_country_codes(
                    indication_str,
                    valid_codes=VALID_COUNTRY_CODES
                )

                # 3a) Build a MultilingualDataCollection for the countries
                country_mld = MultilingualData()
                if country_list:
                    # e.g. "EU, JP, CN"
                    country_mld.add_translation("fr", ", ".join(country_list))
                else:
                    country_mld.add_translation("fr", "")
                country_collection = MultilingualDataCollection()
                country_collection.add_data(country_mld)

                # 4) Build identification key (unchanged)
                identification_key = generate_identification_key(
                    "Sanofi",
                    name_str,
                    indication_str,
                    description_str
                )

                # 5) If `status` exists, append it to description
                if status:
                    if description_str:
                        description_str += "; " + status
                    else:
                        description_str = status

                # 6) Create your MultilingualData objects
                name_mld = MultilingualData()
                name_mld.add_translation("fr", name_str)

                indication_mld = MultilingualData()
                indication_mld.add_translation("fr", cleaned_indication_str)

                description_mld = MultilingualData()
                description_mld.add_translation("fr", description_str)

                therapeutic_area_mld = MultilingualData()
                therapeutic_area_mld.add_translation("fr", therapeutic_area)

                phase_mld = MultilingualData()
                phase_mld.add_translation("fr", phase_str)

                partner_mld = MultilingualData()
                partner_mld.add_translation("fr", collab_str)

                notes_mld = MultilingualData()
                notes_mld.add_translation("fr", notes_str)

                filing_mld = MultilingualData()
                filing_mld.add_translation("fr", submission_str)

                date_updated_mld = MultilingualData()
                date_updated_mld.add_translation("fr", date_last_updated)

                # 7) Convert them to MultilingualDataCollections
                name_collection = MultilingualDataCollection()
                name_collection.add_data(name_mld)

                indication_collection = MultilingualDataCollection()
                indication_collection.add_data(indication_mld)

                description_collection = MultilingualDataCollection()
                description_collection.add_data(description_mld)

                therapeutic_area_collection = MultilingualDataCollection()
                therapeutic_area_collection.add_data(therapeutic_area_mld)

                phase_collection = MultilingualDataCollection()
                phase_collection.add_data(phase_mld)

                partner_collection = MultilingualDataCollection()
                partner_collection.add_data(partner_mld)

                notes_collection = MultilingualDataCollection()
                notes_collection.add_data(notes_mld)

                filing_date_collection = MultilingualDataCollection()
                filing_date_collection.add_data(filing_mld)

                date_updated_collection = MultilingualDataCollection()
                date_updated_collection.add_data(date_updated_mld)

                # 8) Create MasterTable object (assuming you added 'country_codes' field)
                master_record = MasterTable(
                    company_name="Sanofi (French)",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    target=description_collection.get_collection_as_json(),

                    partner=partner_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    filing_date=filing_date_collection.get_collection_as_json(),

                    identification_key=identification_key,
                    date_scraped=date_scraped,
                    date_last_changed=date_updated_collection.get_collection_as_json(),

                    # NEW FIELD (you must ensure your MasterTable class can handle it)
                    country=country_collection.get_collection_as_json()
                )

                # 9) Append the serialized record (or object)
                master_table_list.append(master_record.__dict__)

            except Exception as ex:
                logging.error(
                    f"Error processing a project (projectName={proj.get('projectName')}): {ex}",
                    exc_info=True
                )

        logging.info(f"Processed {len(master_table_list)} unique treatments for Sanofi.")
        return master_table_list

    except Exception as e:
        logging.error(f"An error occurred scraping Sanofi's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Sanofi script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
