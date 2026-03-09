import re
import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

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


async def fetch_biomarin_html():
    """
    Returns the Biomarin pipeline URL (stub).
    """
    try:
        url = "https://www.biomarin.com/products-and-pipeline/research-pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Biomarin pipeline URL: {e}")
        return None


# -------------------------------------------------------------------
# Helper: Extract Footnotes + "Updated ..." from the .smallprint block
# -------------------------------------------------------------------
def extract_footnotes_and_date_updated(soup):
    """
    Dynamically build a map of superscript footnotes found under
    .block.band.pt0 .smallprint, and also scrape the "Updated ..." text.

    Returns:
        footnotes (dict): e.g. { '¹': 'Trial evaluating an expanded indication...', '²': 'Phase 2 enrollment...' }
        date_updated (str): e.g. "September 5, 2024" (if found), otherwise "N/A"
    """
    footnotes = {}
    date_updated = "N/A"

    # Locate the smallprint container
    smallprint_div = soup.select_one(".block.band.pt0 .wrapper .smallprint")
    if not smallprint_div:
        return footnotes, date_updated

    # Each <p> can have a footnote or an "Updated ..." line
    paragraphs = smallprint_div.find_all("p", recursive=False)
    for p in paragraphs:
        text = p.get_text(strip=True)
        if not text:
            continue

        # 1) Check if line starts with a superscript (e.g. ¹, ², ³, etc.)
        #    If so, capture the superscript plus the rest of the line
        match = re.match(r"^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)(.*)", text)
        if match:
            sup = match.group(1).strip()
            explanation = match.group(2).strip()
            footnotes[sup] = explanation

        # 2) Check if this line starts with "Updated ..."
        elif text.lower().startswith("updated "):
            # For example, "Updated September 5, 2024" => date_updated = "September 5, 2024"
            date_updated = text.replace("Updated", "").strip()

    return footnotes, date_updated


# -----------------------------------
# Main Scraping Function
# -----------------------------------
async def process_biomarin_html(html_content):
    """
    Parses Biomarin's pipeline HTML and returns a list of serialized MasterTable objects.
    1) Dynamically extracts footnotes and "Updated ..." from the .smallprint area.
    2) Uses semicolons to separate paragraphs in notes.
    3) Appends footnote text to notes (also separated by semicolons).
    4) Calculates the highest phase with non-zero progress from the 2nd pipeline-phases block.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for BioMarin pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="BioMarin script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')

        # ---------------------------------------------------------
        # 1) Extract footnotes + "Updated ..." from smallprint area
        # ---------------------------------------------------------
        footnotes_map, date_updated = extract_footnotes_and_date_updated(soup)

        # Fallback: If you still want to check another location for date, you could do that here
        # updated_paragraph = soup.select_one('div.field--name-bp-text p.updated-date')
        # if updated_paragraph and updated_paragraph.get_text(strip=True):
        #     date_updated = updated_paragraph.get_text(strip=True)

        # We'll keep date_updated from the smallprint block:
        logging.info(f"Date Updated found in smallprint: {date_updated}")

        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # Phase ordering (lowest to highest)
        phase_order = ["Preclinical", "Phase 1", "Phase 2", "Phase 3"]
        phase_mapping = {
            'pipeline-phase-preclinical': 'Preclinical',
            'pipeline-phase-1': 'Phase 1',
            'pipeline-phase-2': 'Phase 2',
            'pipeline-phase-3': 'Phase 3'
        }

        # Locate each pipeline-listing block
        pipeline_listings = soup.find_all('div', class_='pipeline-listing')
        for listing in pipeline_listings:
            # e.g. "Skeletal Conditions", "Enzyme Therapies", "Innovation", etc.
            therapeutic_area_tag = listing.find('h2')
            therapeutic_area = therapeutic_area_tag.get_text(strip=True) if therapeutic_area_tag else "N/A"

            # Each article is a "pipeline-trial"
            trials = listing.find_all('article', class_='pipeline-trial')
            for trial in trials:

                # ----------------
                # Product Name
                # ----------------
                candidate_div = trial.find('div', class_='pipeline-candidate')
                product_name_tag = candidate_div.find('h3') if candidate_div else None
                product_name_raw = product_name_tag.get_text(strip=True) if product_name_tag else "N/A"

                # Find superscripts in product name
                superscripts_found = re.findall(r'[¹²³⁴⁵⁶⁷⁸⁹⁰]', product_name_raw)

                # For display, remove them from final product name
                product_name_cleaned = re.sub(r'[¹²³⁴⁵⁶⁷⁸⁹⁰]', '', product_name_raw).strip()

                # ----------------
                # Condition (Indication)
                # ----------------
                condition_div = trial.find('div', class_='pipeline-condition')
                condition_p = condition_div.find('p') if condition_div else None
                indications = condition_p.get_text(strip=True) if condition_p else "N/A"

                # ----------------
                # Modality
                # ----------------
                modality_div = trial.find('div', class_='pipeline-modality')
                modality_ul = modality_div.find('ul') if modality_div else None
                modalities = [li.get_text(strip=True) for li in modality_ul.find_all('li')] if modality_ul else []
                modality = ", ".join(modalities) if modalities else "N/A"

                # ----------------
                # Details -> gather paragraphs, separate by semicolons
                # ----------------
                details_div = trial.find('div', class_='pipeline-details')
                all_paragraphs = []
                if details_div:
                    # Gather *all* <p> tags in pipeline-details
                    for p in details_div.find_all('p', recursive=False):
                        paragraph_text = p.get_text(strip=True)
                        if paragraph_text:
                            all_paragraphs.append(paragraph_text)

                # Join with semicolons
                more_info_raw = "; ".join(all_paragraphs) if all_paragraphs else "N/A"

                # Attempt to find a molecule name from the first paragraph
                molecule = "N/A"
                if all_paragraphs:
                    first_para = all_paragraphs[0]
                    molecule_match = re.search(
                        r"evaluating [^,]+,\s+a\s+([^,]+),",
                        first_para,
                        re.IGNORECASE
                    )
                    if molecule_match:
                        molecule = molecule_match.group(1).strip()

                # ----------------
                # Append footnote text (if any) to more_info_raw
                # with semicolons
                # ----------------
                # For each superscript found in product_name_raw, if it's in footnotes_map, add it.
                for sup in superscripts_found:
                    if sup in footnotes_map:
                        if more_info_raw == "N/A":
                            more_info_raw = ""
                        else:
                            more_info_raw += "; "
                        more_info_raw += f"{footnotes_map[sup]}"

                # ----------------
                # Extract phase from second .pipeline-phases container
                # ----------------
                phases_div_candidates = trial.find_all('div', class_='pipeline-phases')
                main_phases_div = None
                for div_candidate in phases_div_candidates:
                    if 'pipeline-inline-phases' not in div_candidate.get('class', []):
                        main_phases_div = div_candidate
                        break

                current_phase = "unknown"
                if main_phases_div:
                    phase_progress = {}
                    phase_divs = main_phases_div.find_all('div', class_='pipeline-phase', recursive=False)

                    for single_phase_div in phase_divs:
                        if 'pipeline-expand' in single_phase_div.get('class', []):
                            continue

                        discovered_phase_name = None
                        for cls in single_phase_div.get('class', []):
                            if cls in phase_mapping:
                                discovered_phase_name = phase_mapping[cls]
                                break
                        if not discovered_phase_name:
                            continue

                        progress_div = single_phase_div.find('div', class_='phase-progress')
                        progress = 0
                        if progress_div:
                            for c_name in progress_div.get('class', []):
                                if 'phase-progress-' in c_name:
                                    try:
                                        progress = int(c_name.split('-')[-1])
                                    except ValueError:
                                        pass

                        phase_progress[discovered_phase_name] = progress

                    # Determine highest phase with progress > 0
                    for ph in reversed(phase_order):
                        if ph in phase_progress and phase_progress[ph] > 0:
                            current_phase = ph
                            break
                else:
                    current_phase = "N/A"

                # ----------------
                # Study Link
                # ----------------
                study_link_tag = trial.find('a', class_='button-external')
                study_link = (
                    study_link_tag['href']
                    if study_link_tag and study_link_tag.has_attr('href')
                    else "N/A"
                )

                # ----------------
                # Compile trial data
                # ----------------
                trial_data = {
                    "Therapeutic Area": therapeutic_area,
                    "product_name": product_name_cleaned,
                    "molecule": molecule,
                    "indications": indications,
                    "phase": current_phase,
                    "date_updated": date_updated,
                    "MoreInfo": more_info_raw,
                    "study_link": study_link
                }

                # ----------------
                # Convert to MasterTable object (+ cleaning)
                # ----------------
                area = clean_text(trial_data["Therapeutic Area"]) if callable(clean_text) else trial_data["Therapeutic Area"]
                program = clean_text(trial_data["product_name"]) if callable(clean_text) else trial_data["product_name"]
                indication = clean_text(trial_data["indications"]) if callable(clean_text) else trial_data["indications"]
                phase_str = clean_phase(trial_data["phase"]) if callable(clean_phase) else trial_data["phase"]
                molecule_clean = clean_text(trial_data["molecule"]) if callable(clean_text) else trial_data["molecule"]
                notes_str = trial_data["MoreInfo"] if callable(clean_text) else trial_data["MoreInfo"]
                date_updated_clean = clean_text(trial_data["date_updated"]) if callable(clean_text) else trial_data["date_updated"]
                study_link_val = trial_data["study_link"]

                identification_key = generate_identification_key(
                    "Biomarin",
                    program,
                    area,
                    indication
                )

                # Build multilingual fields
                area_trans = MultilingualData()
                area_trans.add_translation("en", area)

                program_trans = MultilingualData()
                program_trans.add_translation("en", program)

                indication_trans = MultilingualData()
                indication_trans.add_translation("en", indication)

                phase_trans = MultilingualData()
                phase_trans.add_translation("en", phase_str)

                molecule_trans = MultilingualData()
                molecule_trans.add_translation("en", molecule_clean)

                notes_trans = MultilingualData()
                notes_trans.add_translation("en", notes_str)

                date_updated_trans = MultilingualData()
                date_updated_trans.add_translation("en", date_updated_clean)

                # Wrap them in collections
                area_collection = MultilingualDataCollection()
                program_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()
                molecule_collection = MultilingualDataCollection()
                notes_collection = MultilingualDataCollection()
                date_updated_collection = MultilingualDataCollection()

                area_collection.add_data(area_trans)
                program_collection.add_data(program_trans)
                indication_collection.add_data(indication_trans)
                phase_collection.add_data(phase_trans)
                molecule_collection.add_data(molecule_trans)
                notes_collection.add_data(notes_trans)
                date_updated_collection.add_data(date_updated_trans)

                # Avoid duplicates
                record_key = (
                    area,
                    program,
                    indication,
                    phase_str,
                    molecule_clean,
                    notes_str
                )
                if record_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="BioMarin Pharmaceutical",
                        treatment_name=program_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        therapeutic_area=area_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        target=molecule_collection.get_collection_as_json(),
                        date_scraped=date_scraped,
                        identification_key=identification_key,
                        date_last_changed=date_updated_collection.get_collection_as_json(),
                        notes=notes_collection.get_collection_as_json(),
                        study=study_link_val
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(record_key)

        logging.info(f"Processed {len(treatments)} treatments for Biomarin.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping BioMarin's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in BioMarin script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []