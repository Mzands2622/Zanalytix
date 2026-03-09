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
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import logging
import re


def split_treatment_name_and_notes(treatment_str):
    """
    1) If the string starts with 'farletuzumab ecteribulin' (case-insensitive),
       then treat that entire phrase as the name.
    2) Otherwise, iterate through characters from the beginning, tracking parentheses.
       - If outside parentheses and you hit the first whitespace, split there.
       - If inside parentheses, keep going until the matching closing parenthesis.
       - If no whitespace encountered outside parentheses, entire string is name, notes="".
    """

    # -------------------------------------------------------
    # 1) Check if it starts with "farletuzumab ecteribulin"
    # -------------------------------------------------------
    pattern = re.compile(r'^(farletuzumab\s+ecteribulin)(.*)$', re.IGNORECASE)
    m = pattern.match(treatment_str)
    if m:
        treatment_updated = m.group(1).strip()
        treatment_notes = m.group(2).strip()
        return treatment_updated, treatment_notes

    # -------------------------------------------------------
    # 2) Otherwise, parse parentheses manually
    # -------------------------------------------------------
    treatment_updated = []
    in_paren = False
    paren_depth = 0

    # We'll track the index where we want to split (if we find a valid space outside parentheses)
    split_index = None

    for i, ch in enumerate(treatment_str):
        if ch == '(':
            in_paren = True
            paren_depth += 1
            treatment_updated.append(ch)
        elif ch == ')':
            # Decrement depth; if it goes to zero, we are no longer in parentheses
            paren_depth -= 1
            if paren_depth == 0:
                in_paren = False
            treatment_updated.append(ch)
        elif ch.isspace() and not in_paren:
            # First whitespace outside parentheses
            split_index = i
            break
        else:
            treatment_updated.append(ch)

    if split_index is not None:
        # We have a split point
        name_part = "".join(treatment_updated).strip()
        notes_part = treatment_str[split_index:].strip()
        return name_part, notes_part
    else:
        # No outside-parentheses whitespace => entire string is the name
        return treatment_str, ""


# ----------------------------------
# 2) Fetch HTML Function
# ----------------------------------
async def fetch_eisai_html():
    """
    Fetch HTML for Eisai's pipeline using Zyte, scrolling to bottom and waiting for dynamic content.
    """
    try:
        # Eisai pipeline URL
        url = "https://www.eisai.com/innovation/research/pipeline/index.html"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Eisai pipeline HTML: {e}", exc_info=True)
        return None


# ----------------------------------
# 3) Process HTML Function
# ----------------------------------
async def process_eisai_html(html_content):
    """
    Parses Eisai's pipeline HTML and returns a list of serialized MasterTable objects
    that mirror the structure used in the reference script.
    """
    key_count = 1

    try:
        if not html_content:
            logging.warning("No HTML content received for Eisai pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Eisai script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # --------------------------------------------------
        # 1) Extract the "As of" date and clean it right away
        # --------------------------------------------------
        as_of_date_raw = ""
        date_p = soup.find("p", class_="txt-right")
        if date_p:
            as_of_date_raw = date_p.get_text(separator=" ", strip=True)
        as_of_date = clean_text(as_of_date_raw)  # Clean the date string

        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # -------------------------------------------------------------------------
        # 2) Each <h3 class="hdg-03"> is a therapeutic area heading, then a table
        # -------------------------------------------------------------------------
        area_headings = soup.select("h3.hdg-03")
        for heading in area_headings:
            # Clean the therapeutic area name
            therapeutic_area_raw = heading.get_text(strip=True)
            therapeutic_area = clean_text(therapeutic_area_raw)

            # Find the next .scrollable-tbl
            scroll_div = heading.find_next("div", class_="scrollable-tbl")
            if not scroll_div:
                continue

            table = scroll_div.find("table", class_="tbl-02")
            if not table:
                continue

            # Check if it's a "Global Health" table or a standard pipeline table
            first_row = table.find("tr")
            if not first_row:
                continue

            all_th_in_first = first_row.find_all("th")
            is_global_health = any(
                "sponsor of study" in th.get_text(strip=True).lower()
                for th in all_th_in_first
            )

            tbody = table.find("tbody")
            if not tbody:
                continue

            current_treatment = None
            last_disease = None
            last_study = None

            rows = tbody.find_all("tr")
            for row in rows:
                # Check if this row is a sub-header for a new treatment
                sub_header_th = row.find("th", class_="tbl-hdg-sub")
                if sub_header_th:
                    current_treatment_raw = sub_header_th.get_text(separator=" ", strip=True)
                    current_treatment = clean_text(current_treatment_raw)
                    # Reset last disease/study each time a new sub-header appears
                    last_disease = None
                    last_study = None
                    continue

                # Grab the cells
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                # If it looks like a header row (e.g. "Disease Study Region..."), skip
                joined_text = " ".join(clean_text(cell.get_text(strip=True).lower()) for cell in cells)
                if ("disease" in joined_text and "region" in joined_text) or \
                   ("sponsor of study" in joined_text and "region" in joined_text):
                    continue

                # =============== If Global Health table ===============
                if is_global_health:
                    # Typically 4 or 5 columns in practice
                    if len(cells) == 4 and cells[0].get("colspan") == "2":
                        disease_raw = cells[0].get_text(separator=" ", strip=True)
                        sponsor_raw = cells[1].get_text(separator=" ", strip=True)
                        region_raw = cells[2].get_text(separator=" ", strip=True)
                        dev_stage_raw = cells[3].get_text(separator=" ", strip=True)

                    elif len(cells) == 5:
                        disease_raw = cells[0].get_text(separator=" ", strip=True)
                        sponsor_raw = cells[2].get_text(separator=" ", strip=True)
                        region_raw = cells[3].get_text(separator=" ", strip=True)
                        dev_stage_raw = cells[4].get_text(separator=" ", strip=True)
                    else:
                        # Unexpected row format => skip
                        continue

                    # Clean them all
                    disease = clean_text(disease_raw)
                    sponsor = clean_text(sponsor_raw)
                    region = clean_text(region_raw)
                    dev_stage = clean_phase(dev_stage_raw)

                    study = "N/A"
                    indicator = "N/A"
                    notes_raw = f"Sponsor: {sponsor}, Region: {region}"
                    notes = clean_text(notes_raw)
                    phase = clean_phase(dev_stage) # If needed, could apply `clean_phase` here

                # =============== Else standard table ===============
                else:
                    if len(cells) == 5:
                        disease_raw = cells[0].get_text(strip=True)
                        study_raw = cells[1].get_text(strip=True)
                        region_raw = cells[2].get_text(strip=True)
                        indicator_raw = cells[3].get_text(strip=True)
                        dev_stage_raw = cells[4].get_text(separator=" ", strip=True)

                        # Clean them
                        disease = clean_text(disease_raw)
                        study = clean_text(study_raw)
                        region = clean_text(region_raw)
                        indicator = clean_text(indicator_raw)
                        dev_stage = clean_phase(dev_stage_raw)

                        # Remember for subsequent rows
                        last_disease = disease
                        last_study = study

                    elif len(cells) == 3:
                        # Reuse last_disease and last_study
                        region_raw = cells[0].get_text(strip=True)
                        indicator_raw = cells[1].get_text(strip=True)
                        dev_stage_raw = cells[2].get_text(separator=" ", strip=True)

                        # Clean them
                        disease = last_disease
                        study = last_study
                        region = clean_text(region_raw)
                        indicator = clean_text(indicator_raw)
                        dev_stage = clean_phase(dev_stage_raw)
                    else:
                        # Unexpected row format => skip
                        continue

                    # Replace special indicators if needed
                    if indicator == '●':
                        indicator = "Development progress from April 2024 onwards"
                    elif indicator == '○':
                        indicator = "Development progress from July 2024 onwards"

                    notes = clean_text(indicator)
                    phase = dev_stage

                # -------------------------------------------------------------------------
                # 3) At this point, you have:
                #    - current_treatment   (the full, cleaned treatment string)
                #    - disease, region, study, phase, etc.
                # -------------------------------------------------------------------------

                treatment_name = current_treatment or "N/A"

                # a) Generate identification key (assuming "Eisai" as company name)
                identification_key = generate_identification_key(
                    "Eisai",
                    treatment_name,
                    disease,
                    region,
                    study
                )

                # -----------------------------------------------------------
                # b) NOW split "treatment_name" into two parts after the key
                # -----------------------------------------------------------
                ### NEW ###
                treatment_updated, treatment_notes = split_treatment_name_and_notes(treatment_name)

                treatment_updated = clean_text(treatment_updated)
                
                treatment_updated = re.sub(r'(\S)\(', r'\1 (', treatment_updated)


                treatment_notes = clean_text(treatment_notes)

                if notes:
                    notes += " " + treatment_notes
                else:
                    notes = treatment_notes

                # c) Create your multilingual translators
                ta_translator = MultilingualData()
                ta_translator.add_translation("en", therapeutic_area)

                region_translator = MultilingualData()
                region_translator.add_translation("en", region)

                indication_translator = MultilingualData()
                indication_translator.add_translation("en", disease)

                notes_translator = MultilingualData()
                notes_translator.add_translation("en", notes)

                study_translator = MultilingualData()
                study_translator.add_translation("en", study)

                name_translator = MultilingualData()
                # Store the "treatment_updated" (the first token) instead of the full text
                name_translator.add_translation("en", treatment_updated)

                phase_translator = MultilingualData()
                phase_translator.add_translation("en", phase)

                date_changed_translator = MultilingualData()
                date_changed_translator.add_translation("en", as_of_date)

                # Wrap them in collections
                ta_collection = MultilingualDataCollection()
                ta_collection.add_data(ta_translator)

                region_collection = MultilingualDataCollection()
                region_collection.add_data(region_translator)

                indication_collection = MultilingualDataCollection()
                indication_collection.add_data(indication_translator)

                notes_collection = MultilingualDataCollection()
                notes_collection.add_data(notes_translator)

                study_collection = MultilingualDataCollection()
                study_collection.add_data(study_translator)

                name_collection = MultilingualDataCollection()
                name_collection.add_data(name_translator)


                phase_collection = MultilingualDataCollection()
                phase_collection.add_data(phase_translator)

                date_changed_collection = MultilingualDataCollection()
                date_changed_collection.add_data(date_changed_translator)

                # d) Construct MasterTable object
                #    You can store the "treatment_updated" or the entire "current_treatment",
                #    plus "treatment_notes" if you want a separate field in MasterTable.
                treatment_key = (
                    therapeutic_area,
                    treatment_name,  # or treatment_updated
                    disease,
                    phase,
                    notes
                )

               
                
                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Eisai",
                        therapeutic_area=ta_collection.get_collection_as_json(),
                        # If you only want the first token, use the name_collection here:
                        treatment_name=name_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        phase=phase_collection.get_collection_as_json(),
                        notes=notes_collection.get_collection_as_json(),
                        study=study_collection.get_collection_as_json(),
                        date_scraped=date_scraped,
                        identification_key=identification_key,
                        date_last_changed=date_changed_collection.get_collection_as_json(),
                        country=region_collection.get_collection_as_json(),
                    )

                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Eisai.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Eisai's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Eisai script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
