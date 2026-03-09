import asyncio
import aiohttp
import logging
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# =============================================
# Footnote / Partnership / Abbrev Parsing Logic
# =============================================

def parse_partnership_data(html: str) -> dict:
    """
    Finds the <p> element that contains "Development Partnership:".
    Then parses each "Compound: Partner;" pair.

    Example text might look like:
      "Development Partnership: AUGTYRO: Zai Lab; EGFRxHER3 ADC: SystImmune; ...
       OPDIVO, YERVOY, OPDUALAG: Ono; PKCθ Inhibitor: Exscientia; ..."

    Returns a dictionary, for example:
      {
        "AUGTYRO": "Zai Lab",
        "EGFRxHER3 ADC": "SystImmune",
        "OPDIVO": "Ono",
        "YERVOY": "Ono",
        "OPDUALAG": "Ono",
        "PKCθ Inhibitor": "Exscientia",
        ...
      }
    """
    partnership_dict = {}
    soup = BeautifulSoup(html, "html.parser")

    # 1) Find the <p> that contains "Development Partnership:"
    dev_partnership_text = None
    for p in soup.find_all("p"):
        text_in_p = p.get_text(separator=" ", strip=True)
        if "Development Partnership:" in text_in_p:
            dev_partnership_text = text_in_p
            break

    if not dev_partnership_text:
        return partnership_dict

    # 2) Extract the substring after "Development Partnership:"
    try:
        start_idx = dev_partnership_text.index("Development Partnership:") + len("Development Partnership:")
        snippet = dev_partnership_text[start_idx:].strip()
    except ValueError:
        return partnership_dict

    # 3) Regex that allows ANY characters until the colon, then ANY until the semicolon
    pattern = re.compile(r'([^:]+):\s*([^;]+);')
    matches = pattern.findall(snippet)

    for compound, partner in matches:
        # Strip whitespace
        compound = compound.strip()
        partner = partner.strip()

        # If the compound string contains commas (e.g. "OPDIVO, YERVOY, OPDUALAG"),
        # split them so each becomes a separate key in the dictionary.
        sub_compounds = [c.strip() for c in compound.split(",")]

        for c in sub_compounds:
            partnership_dict[c] = partner

    return partnership_dict


def parse_footnotes(html: str) -> dict:
    """
    Finds the <p> that contains the phrase "Partner-run study" anywhere in its text.
    Then splits that <p> on <br> to capture lines like:
       * Partner-run study
       ◊ Product is marketed as IMNOVID® in the EU
       # Japan only
       ✦ NME Lead Indication

    Returns a dict like: 
      { '*': 'Partner-run study', '◊': 'Product ...' , ... }
    """
    footnotes = {}
    soup = BeautifulSoup(html, "html.parser")

    # 1) Find <p> containing the phrase "Partner-run study"
    footnotes_element = None
    for p in soup.find_all("p"):
        text_in_p = p.get_text()
        if re.search(r"Partner\s*\-?\s*run\s+study", text_in_p, re.IGNORECASE):
            footnotes_element = p
            break

    if not footnotes_element:
        return footnotes

    # 2) Convert that entire <p> to a string, then split on <br> tags
    footnotes_html = str(footnotes_element)
    segments = footnotes_html.split("<br")

    # 3) Regex to see if a line starts with any "non-word" characters as the symbol
    pattern = re.compile(r'^(\W+)\s+(.*)')

    for seg in segments:
        # Remove leftover tags (e.g. <span>, <sup>, etc.)
        clean_line = BeautifulSoup(seg, "html.parser").get_text().strip()
        match = pattern.match(clean_line)
        if match:
            symbol = match.group(1).strip()
            desc = match.group(2).strip()

            # Remove "/>" plus any whitespace
            symbol = re.sub(r'/>\s*', '', symbol)
            symbol = symbol.replace('\n', '').strip()
            if not symbol:
                continue

            footnotes[symbol] = desc

    return footnotes


def parse_abbreviations(html: str) -> dict:
    """
    Extracts abbreviations near the footnotes, e.g.:
       NSCLC = Non-Small Cell Lung Cancer
       SCLC = Small Cell Lung Cancer
       TCE = T-Cell Engager
       ADC = Antibody Drug Conjugate
       ESA = Erythropoiesis-Stimulating Agent

    Returns a dict like:
      { "NSCLC": "Non-Small Cell Lung Cancer", "SCLC": "Small Cell Lung Cancer", ... }
    """
    abbreviations = {}
    pattern = re.compile(r'(NSCLC|SCLC|TCE|ADC|ESA)\s*=\s*([^<]+)')
    matches = pattern.findall(html)

    for abbr, meaning in matches:
        abbreviations[abbr.strip()] = meaning.strip()

    return abbreviations


def build_footnotes_map(html: str) -> dict:
    """
    Orchestrates the parsing:
      - Partnerships
      - Footnotes
      - Abbreviations
    Then merges everything into a single dictionary.
    """
    partnership_map = parse_partnership_data(html)
    footnotes_map = parse_footnotes(html)
    abbreviations_map = parse_abbreviations(html)

    combined_map = {}

    # Merge Partnerships
    for k, v in partnership_map.items():
        combined_map[k] = v

    # Merge Footnotes
    for k, v in footnotes_map.items():
        combined_map[k] = v

    # Merge Abbreviations
    for k, v in abbreviations_map.items():
        combined_map[k] = v

    return combined_map


# =============================================
# Normalization Function for Footnote Matching
# =============================================
def normalize_for_footnote_match(text: str) -> str:
    """
    Removes trademark symbols, optional punctuation, etc., and lower-cases the text.
    This helps 'Opdualag' in the map match 'OpdualagTM' or 'Opdualag™' in the HTML.
    """
    if not text:
        return ""
    # Remove common trademark symbols
    text = text.replace("™", "").replace("TM", "").replace("®", "")
    # Convert to lowercase
    text = text.lower()
    # You could also remove punctuation or do more advanced cleaning here.
    return text.strip()


# =============================================
# Imports from your function_app
# (Adjust the import path if needed)
# =============================================
from function_app import (
    fetch_with_zyte,        # for asynchronous Zyte fetch
    clean_phase,            # your existing custom function
    clean_text,             # your existing custom function
    MasterTable,            # your data model class
    MultilingualData,       # your multilingual data helper
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# -----------------------
# Fetch BMS HTML
# -----------------------
async def fetch_bms_html():
    """
    Returns the BMS pipeline URL. (If you actually need the HTML content here,
    you could call `fetch_with_zyte(url)` directly in this function.)
    """
    try:
        url = "https://www.bms.com/researchers-and-partners/in-the-pipeline.html"
        return url
    except Exception as e:
        logging.error(f"Error fetching BMS pipeline HTML: {e}")
        return None

# -----------------------
# Process HTML Function
# -----------------------
async def process_bms_html(html_content):
    """
    Parses the BMS pipeline HTML and returns a list of serialized MasterTable objects.
    Now also incorporates a "footnotes map" to detect and attach footnote references
    in a new "notes" field for each record. We check footnotes on the raw text first
    (before `clean_text`), but we do substring matching using a normalization approach
    so that 'Opdualag' matches 'OpdualagTM' or 'Opdualag™', etc.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Bristol-Myers Squibb pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Bristol-Myers Squibb script returned no HTML content. Please investigate!"
            )
            return []

        # 1) Build the footnotes/partnership/abbreviations map
        footnotes_map = build_footnotes_map(html_content)
        logging.info(f"Built footnotes_map => {footnotes_map}")

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()

        # Attempt to locate the last-changed date
        date_element = soup.select_one(".page-callout .body-1")
        date_last_changed = date_element.text.strip() if date_element else "Date not found"

        # Variables to track context while parsing
        previous_treatment = ""
        current_header = ""
        current_subheader = ""

        # Iterate over all elements in the document
        for element in soup.find_all(True):
            # Check for top-level category headings
            if 'category-heading' in element.get('class', []):
                current_header = element.get_text(strip=True)
                current_subheader = ""  # Reset subheader

            # Check for sub-category headings
            elif 'sub-category-heading' in element.get('class', []):
                current_subheader = element.get_text(strip=True)

            # Identify pipeline-listing blocks
            if 'pipeline-listing' in element.get('class', []):
                treatment_info = {
                    'Header': current_header,
                    'Subheader': current_subheader if current_subheader else current_header,
                }

                # Compound Name
                name_block = element.find('div', class_='pipeline-data')
                if name_block:
                    treatment_info['Compound Name'] = name_block.get_text(strip=True)

                # Therapeutic Area
                therapy_block = element.find('div', class_='pipeline-data-block-opacity-text')
                if therapy_block:
                    treatment_info['Therapeutic Area'] = therapy_block.get_text(strip=True)

                # Phases (count the number of .phase-listing divs)
                phases = element.find_all('div', class_='phase-listing')
                phase_info = [phase.get_text(strip=True) for phase in phases]
                treatment_info["Phase"] = len(phase_info)

                # Fix if compound name == therapeutic area
                if (
                    'Compound Name' in treatment_info
                    and 'Therapeutic Area' in treatment_info
                    and treatment_info['Compound Name'] == treatment_info['Therapeutic Area']
                ):
                    treatment_info['Compound Name'] = previous_treatment

                if 'Compound Name' in treatment_info:
                    previous_treatment = treatment_info['Compound Name']

                treatment_info['date_last_changed'] = date_last_changed

                # -------------------------------------
                # A) Get RAW fields (unmodified)
                # -------------------------------------
                raw_brand_name = treatment_info.get('Compound Name', '')
                raw_header = treatment_info.get('Header', '')
                raw_subheader = treatment_info.get('Subheader', '')
                raw_phase = str(treatment_info.get('Phase', ''))
                raw_research_area = treatment_info.get('Therapeutic Area', '')

                # -------------------------------------
                # B) Footnote detection on RAW text (with normalization)
                # -------------------------------------
                notes_list = []
                fields_to_check = [
                    raw_brand_name,
                    raw_research_area,
                    raw_subheader,
                    raw_header,
                    raw_phase
                ]

                # For each key in footnotes_map, we normalize both sides
                for symbol, footnote_text in footnotes_map.items():
                    symbol_norm = normalize_for_footnote_match(symbol)
                    matched = False

                    for field in fields_to_check:
                        field_norm = normalize_for_footnote_match(field)
                        if symbol_norm in field_norm:
                            notes_list.append(f"{symbol}: {footnote_text}")
                            matched = True
                            break  # Found a match, move to next symbol

                notes_str = "; ".join(notes_list).strip()

                # Wrap the notes in multilingual objects
                notes_translator = MultilingualData()
                notes_translator.add_translation("en", notes_str)
                notes_collection = MultilingualDataCollection()
                notes_collection.add_data(notes_translator)

                # -------------------------------------
                # C) Now CLEAN the fields
                # -------------------------------------
                brand_name_compound = clean_text(raw_brand_name)
                therapeutic_area = clean_text(raw_header)
                disease_area = clean_text(raw_subheader)
                phase_str = clean_phase(raw_phase)  # convert to string + optional cleaning
                research_area_line_of_therapy = clean_text(raw_research_area)

                # -------------------------------------
                # D) Generate identification key, etc.
                # -------------------------------------
                identification_key = generate_identification_key(
                    "Bristol-Myers Squibb",
                    brand_name_compound,
                    research_area_line_of_therapy,
                    disease_area
                )

                treatment_key = (
                    therapeutic_area,
                    disease_area,
                    brand_name_compound,
                    phase_str,
                    research_area_line_of_therapy
                )

                # Create multilingual translations
                therapeutic_area_translator = MultilingualData()
                therapeutic_area_translator.add_translation("en", therapeutic_area)

                research_area_translator = MultilingualData()
                research_area_translator.add_translation("en", research_area_line_of_therapy)

                disease_area_translator = MultilingualData()
                disease_area_translator.add_translation("en", disease_area)

                brand_name_translator = MultilingualData()
                brand_name_translator.add_translation("en", brand_name_compound)

                phase_translator = MultilingualData()
                phase_translator.add_translation("en", phase_str)

                date_updated_translator = MultilingualData()
                date_updated_translator.add_translation("en", date_last_changed)

                therapeutic_area_collection = MultilingualDataCollection()
                research_area_collection = MultilingualDataCollection()
                disease_area_collection = MultilingualDataCollection()
                brand_name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()
                date_updated_collection = MultilingualDataCollection()

                therapeutic_area_collection.add_data(therapeutic_area_translator)
                research_area_collection.add_data(research_area_translator)
                disease_area_collection.add_data(disease_area_translator)
                brand_name_collection.add_data(brand_name_translator)
                phase_collection.add_data(phase_translator)
                date_updated_collection.add_data(date_updated_translator)

                # -------------------------------------
                # E) Only add if it's a unique treatment
                # -------------------------------------
                if treatment_key not in processed_treatments:
                    date_scraped = datetime.now(timezone.utc)
                    master_record = MasterTable(
                        company_name="Bristol-Myers Squibb",
                        therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                        treatment_name=brand_name_collection.get_collection_as_json(),
                        indication=research_area_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        date_scraped=date_scraped,
                        date_last_changed=date_updated_collection.get_collection_as_json(),
                        identification_key=identification_key,
                        disease_area=disease_area_collection.get_collection_as_json(),
                        notes=notes_collection.get_collection_as_json()  # attach footnotes
                    )

                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for BMS.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Bristol-Myers Squibb's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Bristol-Myers Squibb's script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
