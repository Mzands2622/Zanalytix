import logging
import re
from bs4 import BeautifulSoup, Comment
from bs4 import element
from datetime import datetime, timezone

# --------------------------------------------
# Import your needed functions/classes here:
# --------------------------------------------
from function_app import (
    fetch_with_zyte,
    clean_phase,
    clean_text,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# -----------------------
# 1) Fetch HTML Function
# -----------------------
async def fetch_silence_html():
    """
    Returns the Silence Therapeutics pipeline URL.
    """
    try:
        url = "https://silence-therapeutics.com/our-pipeline/default.aspx"
        return url
    except Exception as e:
        logging.error(f"Error fetching Silence Therapeutics pipeline URL: {e}")
        return None


# -----------------------
# 2) Process HTML Function
# -----------------------
async def process_silence_html(html_content):
    """
    Parses the Silence Therapeutics pipeline HTML and
    returns a list of serialized MasterTable objects (dicts).
    """

    # -----------------------
    # Early exit if no HTML
    # -----------------------
    if not html_content:
        logging.warning("No HTML content received for Silence Therapeutics pipeline.")
        send_sms(
            phone_number="9144334333",
            message="Silence script returned no HTML content. Please investigate!"
        )
        return []

    try:
        # ~~~~~~~~~ HELPER FUNCTIONS (inline) ~~~~~~~~~

        def parse_footnotes(soup: BeautifulSoup) -> dict:
            """
            Look for footnotes in <p> tags that begin with a non-alphanumeric symbol,
            e.g., '*', '†', '#', etc. Returns { symbol -> note_text }.
            """
            footnotes_map = {}
            # These p-tags typically have .js--animated.fadeInUp in Silence's pipeline
            candidate_paragraphs = soup.select("p.js--animated.fadeInUp")

            pattern = re.compile(r"^([^A-Za-z0-9]+)\s*(.*)$")
            for p_tag in candidate_paragraphs:
                raw_text = p_tag.get_text(strip=True)
                match = pattern.match(raw_text)
                if match:
                    symbol = match.group(1).strip()     # e.g., '*'
                    note_text = match.group(2).strip()  # e.g., "Silence retains exclusive rights..."
                    footnotes_map[symbol] = note_text
            return footnotes_map

        def interpret_phase(percent_str: str) -> str:
            """
            Convert a numeric string like '23%' to one of:
              0–15 -> 'Discovery'
              15–30 -> 'Preclinical'
              30–45 -> 'Phase I'
              45–60 -> 'Phase II'
              >60  -> 'Phase III'
            """
            num_str = percent_str.replace("%", "").strip()
            try:
                value = float(num_str)
            except ValueError:
                return "Unknown"

            if value <= 15:
                return "Discovery"
            elif value <= 30:
                return "Preclinical"
            elif value <= 45:
                return "Phase I"
            elif value <= 60:
                return "Phase II"
            else:
                return "Phase III"

        def split_on_hr(cell) -> list[str]:
            """
            Returns a list of text chunks from .module-pipeline_cell,
            splitting on real <hr> tags (NOT commented-out <hr>).
            Uses recursive traversal so nested <hr> won't get missed.
            """
            # Remove all HTML comments so they don't interfere
            for comment in cell.find_all(string=lambda c: isinstance(c, Comment)):
                comment.extract()

            segments = []
            current_text_parts = []

            def traverse(node):
                nonlocal segments, current_text_parts
                if isinstance(node, element.Tag):
                    if node.name.lower() == 'hr':
                        # Close current segment
                        joined = " ".join(part.strip() for part in current_text_parts if part.strip())
                        if joined:
                            segments.append(joined)
                        current_text_parts = []
                    else:
                        for child in node.children:
                            traverse(child)
                elif isinstance(node, element.NavigableString):
                    txt = node.strip()
                    if txt:
                        current_text_parts.append(txt)

            # Traverse
            for child in cell.children:
                traverse(child)

            # Final flush
            joined = " ".join(part.strip() for part in current_text_parts if part.strip())
            if joined:
                segments.append(joined)

            return segments

        # ~~~~~~~~~~ MAIN PARSE LOGIC ~~~~~~~~~~
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Build footnotes map
        footnotes_map = parse_footnotes(soup)
        footnote_symbols = list(footnotes_map.keys())

        # 2. Locate pipeline rows
        pipeline_rows = soup.select("div.module-pipeline_row.grid--no-gutter")

        parsed_results = []

        for row in pipeline_rows:
            left_col = row.select_one("div.module-pipeline_col--first")
            if not left_col:
                continue

            # We expect 3 cells: [0]=treatment, [1]=indication, [2]=target
            cells_left = left_col.select(".module-pipeline_cell")
            if len(cells_left) < 3:
                continue

            # Get data from each cell, split on <hr>
            treatments = split_on_hr(cells_left[0])
            indications = split_on_hr(cells_left[1])
            targets = split_on_hr(cells_left[2])

            # Right side => progress bars
            right_col = row.select_one("div.module-pipeline_col--progress")
            if not right_col:
                continue
            progress_bars = right_col.select(".module-pipeline_progress--percent")

            num_entries = max(
                len(treatments),
                len(indications),
                len(targets),
                len(progress_bars)
            )

            for i in range(num_entries):
                treatment = treatments[i] if i < len(treatments) else treatments[-1]
                indication = indications[i] if i < len(indications) else indications[-1]
                target = targets[i] if i < len(targets) else targets[-1]

                # Try to get a numeric style or data-position
                progress_value = ""
                if i < len(progress_bars):
                    bar = progress_bars[i]
                    style_value = bar.get("style", "")
                    data_position = bar.get("data-position", "")
                    if "width:" in style_value:
                        # e.g. style="width: 23%;"
                        progress_value = style_value.split("width:")[-1].strip().rstrip(";").strip()
                    elif data_position:
                        progress_value = data_position + "%"

                # Our custom numeric => textual phase
                raw_phase = interpret_phase(progress_value)
                # Then we further clean it with your existing clean_phase() if you like:
                phase = clean_phase(raw_phase)

                # Check for footnote symbol at end of the treatment
                note_text = ""
                for symbol in footnote_symbols:
                    if treatment.endswith(symbol):
                        # remove that symbol
                        treatment = treatment[: -len(symbol)].rstrip()
                        note_text = footnotes_map[symbol]
                        break

                # ~~~~ Use your clean_text ~~~~
                treatment = clean_text(treatment)
                indication = clean_text(indication)
                target = clean_text(target)
                note_text = clean_text(note_text)

                entry = {
                    "treatment": treatment,
                    "indication": indication,
                    "target": target,
                    "phase": phase,
                    "notes": note_text
                }
                parsed_results.append(entry)

        # 3. Convert each dictionary into a MasterTable-based record
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in parsed_results:
            treatment_str = entry["treatment"]
            indication_str = entry["indication"]
            target_str = entry["target"]
            phase_str = entry["phase"]
            notes_str = entry["notes"]

            identification_key = generate_identification_key(
                "SilenceTherapeutics",
                treatment_str,
                indication_str,
                target_str
            )

            # Build multilingual data
            treat_data = MultilingualData()
            treat_data.add_translation("en", treatment_str)

            indic_data = MultilingualData()
            indic_data.add_translation("en", indication_str)

            target_data = MultilingualData()
            target_data.add_translation("en", target_str)

            phase_data = MultilingualData()
            phase_data.add_translation("en", phase_str)

            notes_data = MultilingualData()
            notes_data.add_translation("en", notes_str)

            # Collections
            treat_coll = MultilingualDataCollection()
            indic_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            treat_coll.add_data(treat_data)
            indic_coll.add_data(indic_data)
            target_coll.add_data(target_data)
            phase_coll.add_data(phase_data)
            notes_coll.add_data(notes_data)

            unique_key = (treatment_str, indication_str, target_str, phase_str, notes_str)
            if unique_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Silence Therapeutics",
                    treatment_name=treat_coll.get_collection_as_json(),
                    indication=indic_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(unique_key)

        logging.info(f"Processed {len(treatments)} pipeline entries for Silence Therapeutics.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Silence Therapeutics Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Silence script: {e}. Please investigate!"
        )
        return []
