import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import logging

from function_app import (
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    fetch_with_zyte,
    send_sms
)

# 1) Regex to detect parentheses: e.g., "Name (CD40L blocker)"
PARENS_REGEX = re.compile(r"^(?P<name>.*?)\s*\((?P<target>[^)]+)\)\s*$")

# 2) Regex to detect Unicode superscript digits.
#    This pattern looks for digits in U+00B2..U+00B9 plus U+2070..U+209F, etc.
SUPER_DIGITS_REGEX = re.compile(r"[\u00B2-\u00B9\u00BA\u2070-\u209F]+")

# 3) Optional map for converting superscript characters to normal digits.
#    e.g., '⁹' -> '9', '⁵' -> '5'
SUPER_DIGIT_MAP = {
    '⁰': '0', '¹': '1', '²': '2', '³': '3',
    '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7',
    '⁸': '8', '⁹': '9'
}

def normalize_superscript_digits(text: str) -> str:
    """
    Convert any superscript digits in 'text' to normal ASCII digits.
    E.g., "Lu AG22515 (CD40L blocker)⁹" -> "Lu AG22515 (CD40L blocker)9"
    """
    def _replace(match):
        superscripts = match.group(0)  # e.g. '⁹', '³⁴', etc.
        # Convert each superscript character individually
        converted = ''.join(SUPER_DIGIT_MAP.get(ch, '') for ch in superscripts)
        return converted

    return SUPER_DIGITS_REGEX.sub(_replace, text)

async def fetch_lundbeck_html():
    try:
        # Fetch HTML using Zyte or another method
        url = "https://www.lundbeck.com/global/our-science/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Lundbeck HTML: {e}")
        return None

async def process_lundbeck_html(html_content):
    try:
        if not html_content:
            logging.warning("No HTML content received for Lundbeck pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Lundbeck script returned no HTML content. Please investigate!"
            )
            return []

        treatments = []
        processed_treatments = set()
        soup = BeautifulSoup(html_content, "html.parser")

        # A) Parse footnotes from the <ol> block into a dictionary.
        footnotes_div = soup.select_one("div.cmp-text ol")
        footnotes_dict = {}
        if footnotes_div:
            li_tags = footnotes_div.find_all("li")
            for idx, li in enumerate(li_tags, start=1):
                footnote_text = li.get_text(strip=True)
                footnotes_dict[str(idx)] = footnote_text

        # B) Grab both pipeline tables ("c-table--advanced c-table--pipeline")
        #    and potential section titles ("div.title.display-3").
        selector = (
            "div.title.display-3, "
            "div.c-table--advanced.c-table--pipeline"
        )
        elements = soup.select(selector)
        current_section_title = ""

        for el in elements:
            # 1) If this is a section title
            if "title" in el.get("class", []) and "display-3" in el.get("class", []):
                h_tag = el.select_one("h1.cmp-title__text")
                current_section_title = clean_text(h_tag.get_text(strip=True) if h_tag else "")

            # 2) If this is one of the pipeline tables
            elif "c-table--advanced" in el.get("class", []) and "c-table--pipeline" in el.get("class", []):
                real_table = el.find("table")
                if not real_table:
                    continue

                rows = real_table.find_all("tr")
                # Exclude table header rows
                data_rows = [
                    r for r in rows 
                    if not r.get("class") or "c-table__header-row" not in r.get("class")
                ]

                for row in data_rows:
                    # Grab the "Project" cell (a <th>)
                    project_th = row.find("th", {"data-label": "Project"})
                    if project_th:
                        # Raw text (including parentheses, footnotes, etc.)
                        project_raw = project_th.get_text()
                    else:
                        project_raw = ""

                    # Grab the "Area" cell (a <td>)
                    area_td = row.find("td", {"data-label": "Area"})
                    area_raw = area_td.get_text(strip=True) if area_td else ""

                    # Determine the phase by checking columns “Phase 1 / 2 / 3 / Filing”
                    phase_str = ""
                    phase_1_td = row.find("td", {"data-label": "Phase 1"})
                    if phase_1_td and phase_1_td.find("span", class_="c-table__phase-star"):
                        phase_str = "1"

                    phase_2_td = row.find("td", {"data-label": "Phase 2"})
                    if phase_2_td and phase_2_td.find("span", class_="c-table__phase-star"):
                        phase_str = "2"

                    phase_3_td = row.find("td", {"data-label": "Phase 3"})
                    if phase_3_td and phase_3_td.find("span", class_="c-table__phase-star"):
                        phase_str = "3"

                    filing_td = row.find("td", {"data-label": "Filing"})
                    if filing_td and filing_td.find("span", class_="c-table__phase-star"):
                        phase_str = "Filing"

                    # Mobile column "Phase"
                    if not phase_str:
                        phase_mobile_td = row.find("td", {"data-label": "Phase"})
                        if phase_mobile_td:
                            possible_phase = phase_mobile_td.get_text(strip=True)
                            # If it's "1","2","3", or "Filing"
                            if possible_phase in ["1", "2", "3"]:
                                phase_str = possible_phase
                            elif "Filing" in possible_phase:
                                phase_str = "Filing"
                            else:
                                phase_str = "Unknown"

                    # (Optional) If you want to call clean_phase
                    phase_str = clean_phase(phase_str)

                    # If we don't have a section title, project name, and area, skip
                    if not all([current_section_title, project_raw, area_raw]):
                        logging.warning("Skipping entry due to missing key components.")
                        continue

                    # C) Footnotes:
                    #    Detect superscript digits in the project text.
                    #    Convert them to normal ASCII digits. Then look them up in footnotes_dict.
                    notes_list = []
                    super_matches = SUPER_DIGITS_REGEX.findall(project_raw)
                    for sm in super_matches:
                        # e.g. "⁹" => "9"
                        normalized_digit = SUPER_DIGIT_MAP.get(sm[-1], "")  # take the last char
                        if normalized_digit in footnotes_dict:
                            notes_list.append(footnotes_dict[normalized_digit])
                    notes_text = "\n".join(notes_list) if notes_list else "N/A"

                    # D) Remove superscripts from the project text
                    #    so we can parse parentheses safely.
                    project_no_supers = SUPER_DIGITS_REGEX.sub("", project_raw).strip()

                    # E) Attempt to parse parentheses => “target”
                    target_text = "N/A"
                    parens_match = PARENS_REGEX.match(project_no_supers)
                    if parens_match:
                        project_text = parens_match.group("name").strip()
                        target_text = parens_match.group("target").strip()
                    else:
                        project_text = project_no_supers

                    # Clean up final textual fields
                    project_text = clean_text(project_text)
                    area_text = clean_text(area_raw)

                    # F) Create multilingual data
                    section_translator = MultilingualData()
                    project_translator = MultilingualData()
                    area_translator = MultilingualData()
                    target_translator = MultilingualData()
                    notes_translator = MultilingualData()
                    phase_translator = MultilingualData()

                    section_translator.add_translation("en", current_section_title)
                    project_translator.add_translation("en", project_text)
                    area_translator.add_translation("en", area_text)
                    target_translator.add_translation("en", clean_text(target_text))
                    notes_translator.add_translation("en", clean_text(notes_text))
                    phase_translator.add_translation("en", phase_str)

                    section_collection = MultilingualDataCollection()
                    project_collection = MultilingualDataCollection()
                    area_collection = MultilingualDataCollection()
                    target_collection = MultilingualDataCollection()
                    notes_collection = MultilingualDataCollection()
                    phase_collection = MultilingualDataCollection()

                    section_collection.add_data(section_translator)
                    project_collection.add_data(project_translator)
                    area_collection.add_data(area_translator)
                    if target_text:
                        target_collection.add_data(target_translator)
                    if notes_text:
                        notes_collection.add_data(notes_translator)
                    phase_collection.add_data(phase_translator)

                    # G) Build identification key & create a MasterTable record
                    identification_key = generate_identification_key(
                        "Lundbeck", project_text, area_text, target_text
                    )
                    treatment_key = (
                        current_section_title,
                        project_text,
                        area_text,
                        phase_str,
                        target_text,
                        notes_text,
                    )
                    if treatment_key not in processed_treatments:
                        record = MasterTable(
                            company_name="Lundbeck",
                            therapeutic_area=section_collection.get_collection_as_json(),
                            treatment_name=project_collection.get_collection_as_json(),
                            indication=area_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            date_scraped=datetime.now(timezone.utc),
                            identification_key=identification_key,
                            target=target_collection.get_collection_as_json(),
                            notes=notes_collection.get_collection_as_json() 
                        )
                        treatments.append(record.__dict__)
                        processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Lundbeck.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Lundbeck's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Lundbeck script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []