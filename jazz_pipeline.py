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
from datetime import datetime, timezone
from bs4 import BeautifulSoup, NavigableString
import logging

# -------------------------------------------------
# Helper function to include links in paragraph text
# -------------------------------------------------
def parse_paragraph_with_links(paragraph):
    """
    Returns the text of a <p> element, but includes any links in the form:
    'anchor text (link_url)'
    """
    pieces = []
    for child in paragraph.children:
        if isinstance(child, NavigableString):
            # Just text
            text_part = child.strip()
            if text_part:
                pieces.append(text_part)
        elif child.name == "a":
            # Link with anchor text
            anchor_text = child.get_text(strip=True)
            anchor_url = child.get("href", "").strip()
            if anchor_text:
                # You can adjust the format here if you prefer
                pieces.append(f"{anchor_text} ({anchor_url})")
        else:
            # Could be another tag (e.g., <strong>)
            # We'll just extract its text
            text_part = child.get_text(strip=True)
            if text_part:
                pieces.append(text_part)

    # Join everything with a space (adjust as needed).
    return " ".join(pieces)


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_jazz_html():
    """
    Returns the Jazz Pharmaceuticals pipeline URL.
    """
    try:
        url = "https://www.jazzpharma.com/science/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Jazz pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_jazz_html(html_content):
    """
    Parses the Jazz Pharmaceuticals pipeline HTML and returns
    a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Jazz Pharmaceuticals pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333",
                message="Jazz Pharmaceuticals script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # --------------------------------------
        # 1) Parse the Footnotes Legend (pp-legend)
        # --------------------------------------
        legend_div = soup.find("div", class_="pp-legend")
        footnotes_map = {}
        date_last_changed = None

        if legend_div:
            paragraphs = legend_div.find_all("p")

            # The first paragraph: parse <strong> tags for footnotes
            if len(paragraphs) > 0:
                first_p = paragraphs[0]
                strong_tags = first_p.find_all("strong")
                for strong_tag in strong_tags:
                    abbr = strong_tag.get_text(strip=True)
                    sibling_text = strong_tag.next_sibling
                    if sibling_text:
                        text_str = sibling_text.strip()
                        # Remove leading "= " and trailing commas
                        if text_str.startswith("="):
                            text_str = text_str.lstrip("= ")
                        text_str = text_str.rstrip(", ")
                        footnotes_map[abbr] = text_str

            # The second paragraph: likely "Last Updated January 2025"
            if len(paragraphs) > 1:
                second_p = paragraphs[1].get_text(strip=True)
                date_last_changed = second_p

        logging.info(f"Footnotes Map: {footnotes_map}")
        logging.info(f"Date Last Changed: {date_last_changed}")

        # --------------------------------------
        # 2) Identify major pipeline sections
        # --------------------------------------
        pipeline_sections = soup.find_all("h2", class_="text-purple")
        logging.info(f"Found {len(pipeline_sections)} pipeline sections in Jazz pipeline.")

        # This list will hold all parsed rows (raw) before MasterTable conversion
        all_results = []

        for section in pipeline_sections:
            therapeutic_area = section.get_text(strip=True)
            pipeline_table = section.find_next("table", class_="pipeline-table")
            if not pipeline_table:
                continue

            # Check for nested tables
            sub_tables = pipeline_table.find_all("table", class_="pp-table-secondary")
            if not sub_tables:
                sub_tables = [pipeline_table]

            for st in sub_tables:
                # Each <tbody class="pp-item"> is a pipeline block
                tbodies = st.find_all("tbody", class_="pp-item")

                for tbody in tbodies:
                    current_program = None
                    main_row_dict = None

                    rows = tbody.find_all("tr", recursive=False)
                    for row in rows:
                        row_text = row.get_text(strip=True)
                        if not row_text or row_text == "\xa0":
                            continue  # skip empty rows

                        row_classes = row.get("class", [])

                        # -------------------------
                        # "pipeline-more" → expanded info
                        # -------------------------
                        if "pipeline-more" in row_classes:
                            exp_td = row.find("td", class_="exp-content")
                            if exp_td and main_row_dict:
                                overview_paragraphs = []
                                clinical_trials_paragraphs = []
                                current_section = None

                                paragraphs = exp_td.find_all("p")
                                for p in paragraphs:
                                    strong_el = p.find("strong")
                                    heading_text = (strong_el.get_text(strip=True).upper()
                                                    if strong_el else "")

                                    if heading_text == "OVERVIEW":
                                        current_section = "overview"
                                        continue
                                    elif heading_text == "CLINICAL TRIALS":
                                        current_section = "clinical"
                                        continue

                                    # Parse the text with links
                                    p_text = parse_paragraph_with_links(p)

                                    # Based on current_section, store text
                                    if current_section == "overview":
                                        overview_paragraphs.append(p_text)
                                    elif current_section == "clinical":
                                        clinical_trials_paragraphs.append(p_text)
                                    else:
                                        # If there's no strong heading, treat it as overview
                                        overview_paragraphs.append(p_text)

                                # Store them in main_row_dict
                                main_row_dict["Overview"] = "\n".join(overview_paragraphs).strip()
                                main_row_dict["ClinicalTrials"] = "\n".join(clinical_trials_paragraphs).strip()

                            continue

                        # -------------------------
                        # Recognized data rows
                        # -------------------------
                        if any(cls in row_classes for cls in [
                            "pp-control",
                            "pp-second-line",
                            "sub-item",
                            "w-border-t",
                            "wow"
                        ]):
                            program_td = row.find("td", class_="program")
                            indication_td = row.find("td", class_="indication")
                            phase_td = row.find("td", class_="phase")

                            if program_td:
                                current_program = program_td.get_text(strip=True)

                            indication = indication_td.get_text(strip=True) if indication_td else ""
                            program_name = current_program

                            phase_text = ""
                            if phase_td:
                                md_hidden = phase_td.find("div", class_="md-hidden")
                                if md_hidden:
                                    phase_text = md_hidden.get_text(strip=True)

                            row_dict = {
                                "TherapeuticArea": therapeutic_area,
                                "Program": program_name,
                                "Indication": indication,
                                "Phase": phase_text,
                                "Overview": "",
                                "ClinicalTrials": "",
                                "comment": "",            # We'll populate this later from footnotes_map
                                "date_last_changed": date_last_changed
                            }
                            all_results.append(row_dict)
                            main_row_dict = row_dict

        # --------------------------------------
        # 3) Match abbreviations for 'comment'
        #    (Do this before calling clean_text)
        # --------------------------------------
        for row in all_results:
            raw_program = row["Program"] or ""
            raw_indication = row["Indication"] or ""

            matched_footnotes = []
            for abbr, definition in footnotes_map.items():
                # Simple substring check (case-sensitive). 
                # If you need case-insensitive, use: if abbr.lower() in raw_program.lower()...
                if abbr in raw_program or abbr in raw_indication:
                    matched_footnotes.append(f"{abbr}: {definition}")

            if matched_footnotes:
                # Semicolon-separated, or choose your own format
                row["comment"] = str(matched_footnotes)

        # --------------------------------------------------
        # 4) Convert raw rows into MasterTable objects
        # --------------------------------------------------
        treatments = []
        processed_treatments = set()

        for row in all_results:
            # Only after footnote checks do we 'clean' text
            area = clean_text(row["TherapeuticArea"])
            prog = clean_text(row["Program"])
            indic = clean_text(row["Indication"])
            phase = clean_phase(row["Phase"])
            overview_text = clean_text(row["Overview"])
            clinical_text = clean_text(row["ClinicalTrials"])
            comment_text = row.get("comment", "")  # We'll clean it as well if you want
            comment_text = clean_text(comment_text)
            date_changed_text = row.get("date_last_changed", "")  # e.g. "Last Updated January 2025"

            # Generate a unique key
            identification_key = generate_identification_key(
                "Jazz Pharmaceuticals", prog, area, indic
            )

            # Build MultilingualData for each field
            program_translator = MultilingualData()
            program_translator.add_translation("en", prog)

            indication_translator = MultilingualData()
            indication_translator.add_translation("en", indic)

            area_translator = MultilingualData()
            area_translator.add_translation("en", area)

            notes_translator = MultilingualData()
            notes_translator.add_translation("en", overview_text)

            study_translator = MultilingualData()
            study_translator.add_translation("en", clinical_text)

            phase_translator = MultilingualData()
            phase_translator.add_translation("en", phase)

            # New fields:
            comment_translator = MultilingualData()
            comment_translator.add_translation("en", comment_text)

            date_last_changed_translator = MultilingualData()
            date_last_changed_translator.add_translation("en", date_changed_text)

            # Build collections
            program_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            area_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            comment_collection = MultilingualDataCollection()
            date_changed_collection = MultilingualDataCollection()

            program_collection.add_data(program_translator)
            indication_collection.add_data(indication_translator)
            area_collection.add_data(area_translator)
            notes_collection.add_data(notes_translator)
            study_collection.add_data(study_translator)
            phase_collection.add_data(phase_translator)
            comment_collection.add_data(comment_translator)
            date_changed_collection.add_data(date_last_changed_translator)

            # Prepare final JSON strings (or raw text—depends on MasterTable definition)
            date_scraped = datetime.now(timezone.utc)

            # Deduplicate final entries
            treatment_key = (prog, indic, phase, area, overview_text, clinical_text, comment_text)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Jazz Pharmaceuticals",
                    treatment_name=program_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    identification_key=identification_key,
                    date_scraped=date_scraped,
                    notes=notes_collection.get_collection_as_json(),
                    study=study_collection.get_collection_as_json(),
                    # Add two new fields
                    comment=comment_collection.get_collection_as_json(),
                    date_last_changed=date_changed_collection.get_collection_as_json(),
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Jazz.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Jazz Pharmaceutical's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333",
            message=f"Error in Jazz Pharmaceuticals script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
