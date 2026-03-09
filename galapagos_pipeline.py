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
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import logging

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_galapagos_html():
    """
    Returns the Galapagos pipeline URL.
    """
    try:
        url = "https://www.glpg.com/innovation/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Galapagos pipeline URL: {e}")
        return None


# -----------------------
# Main Scraper Function
# -----------------------
async def process_galapagos_html(html_content):
    """
    Parses the Galapagos pipeline HTML and returns a list of MasterTable objects (as dicts).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Galapagos pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Galapagos script returned no HTML content. Please investigate!"
            )
            return []


        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # --------------------------------------------------------------------
        # 1) Extract "date_updated" from <p class="modification-date">
        # --------------------------------------------------------------------
        date_p = soup.find('p', class_='has-dark-green-color has-text-color has-link-color wp-elements-fae3b9e06a72e1884155f61b48909908')
        date_updated_text = clean_text(date_p.get_text(strip=True)) if date_p else None

        # --------------------------------------------------------------------
        # 2) Get the star note text from the special paragraph:
        #    <p style="font-size: 14px; ...">*Subject to opt-in ...
        # --------------------------------------------------------------------
        star_paragraph = soup.find(
            'p',
            style=lambda x: x is not None and "font-size: 14px;" in x
        )
        star_text = ""
        if star_paragraph and "*Subject to" in star_paragraph.get_text():
            star_text = star_paragraph.get_text(separator=" ", strip=True)

        # --------------------------------------------------------------------
        # 3) For each major 'area' (e.g. Oncology, Immunology):
        #    <div class="area">
        # --------------------------------------------------------------------
        for area_div in soup.find_all('div', class_='area'):
            area_name = clean_text(
                area_div.find('h3', class_='subtitle').get_text(strip=True)
            ) if area_div.find('h3', class_='subtitle') else ""

            # Each pipeline subsection: <div class="area-table">
            for subarea_section in area_div.find_all('div', class_='area-table'):
                # subarea: an optional <h4 class="drugmod-title">
                h4 = subarea_section.find_previous('h4', class_='drugmod-title')
                subarea_name = clean_text(h4.get_text(strip=True)) if h4 else None

                # Each row: <article class="item">
                articles = subarea_section.find_all('article', class_='item')
                for art in articles:
                    left_div = art.find('div', class_='description')
                    if not left_div:
                        continue

                    cols = left_div.find_all('div', class_='col')
                    col_3 = left_div.find('div', class_='col-3')

                    # ---------------------------------------------------------
                    # 3a) Grab the raw text first
                    # ---------------------------------------------------------
                    raw_prod = cols[0].get_text(strip=True) if len(cols) > 0 else ""
                    raw_targ = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                    raw_study = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                    raw_class = cols[3].get_text(strip=True) if len(cols) > 3 else ""

                    # Clean them for final usage
                    product_candidate = clean_text(raw_prod)
                    target = clean_text(raw_targ)
                    study_text = clean_text(raw_study)
                    drug_class = clean_text(raw_class)

                    # ---------------------------------------------------------
                    # 3b) Collect possible indications from col_3
                    # ---------------------------------------------------------
                    main_indications = []
                    if col_3:
                        spans_with_data = col_3.find_all('span', attrs={'data-text': True})
                        if spans_with_data:
                            main_indications = [
                                clean_text(s['data-text']) for s in spans_with_data
                            ]
                        else:
                            plain_spans = col_3.find_all('span')
                            if plain_spans:
                                main_indications = [
                                    clean_text(sp.get_text(strip=True)) for sp in plain_spans
                                ]
                            else:
                                # fallback
                                raw_text_col_3 = clean_text(col_3.get_text(strip=True))
                                if raw_text_col_3:
                                    main_indications = [raw_text_col_3]

                    # ---------------------------------------------------------
                    # 3c) Check if any piece of the raw text has '*'
                    # ---------------------------------------------------------
                    has_star = False
                    if ("*" in raw_prod or "*" in raw_targ or
                        "*" in raw_study or "*" in raw_class):
                        has_star = True

                    # ---------------------------------------------------------
                    # 3d) Parse the "status bars" to get the phase and progress
                    # ---------------------------------------------------------
                    status_bars = art.find_all('div', class_='status-bar')
                    if status_bars:
                        for idx, sb in enumerate(status_bars):
                            status_span = sb.find('span', class_='status')
                            if not status_span or 'data-width' not in status_span.attrs:
                                continue

                            width_str = status_span['data-width']  # e.g. "37.5%"
                            phase, progress_val = get_phase_from_width(width_str)

                            sub_title_elt = sb.find('span', class_='sub-title')
                            if sub_title_elt:
                                sub_indication = clean_text(sub_title_elt.get_text(strip=True))
                            else:
                                # fallback if we have main_indications
                                if idx < len(main_indications):
                                    sub_indication = main_indications[idx]
                                else:
                                    sub_indication = "Unknown"

                            # Build record
                            record = create_mastertable_record(
                                company="Galapagos",
                                area=area_name,
                                subarea=subarea_name,
                                product_candidate=product_candidate,
                                target_text=target,
                                study_text=study_text,
                                drug_class=drug_class,
                                indication_text=sub_indication,
                                phase_text=phase,
                                progress_val=progress_val,
                                date_updated=date_updated_text,
                                date_scraped=date_scraped,
                                notes=star_text if has_star else ""
                            )

                            treatment_key = (
                                record["Therapeutic_Area"],
                                record["Treatment_Name"],
                                record["Indication"],
                                record["Phase"]
                            )
                            if treatment_key not in processed_treatments:
                                treatments.append(record)
                                processed_treatments.add(treatment_key)

                    else:
                        # No status bars => "Unknown" phase
                        if not main_indications:
                            record = create_mastertable_record(
                                company="Galapagos",
                                area=area_name,
                                subarea=subarea_name,
                                product_candidate=product_candidate,
                                target_text=target,
                                study_text=study_text,
                                drug_class=drug_class,
                                indication_text="Unknown",
                                phase_text="Unknown",
                                progress_val=0.0,
                                date_updated=date_updated_text,
                                date_scraped=date_scraped,
                                notes=star_text if has_star else ""
                            )
                            treatment_key = (
                                record["Therapeutic_Area"],
                                record["Treatment_Name"],
                                record["Indication"],
                                record["Phase"]
                            )
                            if treatment_key not in processed_treatments:
                                treatments.append(record)
                                processed_treatments.add(treatment_key)
                        else:
                            for sub_indication in main_indications:
                                record = create_mastertable_record(
                                    company="Galapagos",
                                    area=area_name,
                                    subarea=subarea_name,
                                    product_candidate=product_candidate,
                                    target_text=target,
                                    study_text=study_text,
                                    drug_class=drug_class,
                                    indication_text=sub_indication,
                                    phase_text="Unknown",
                                    progress_val=0.0,
                                    date_updated=date_updated_text,
                                    date_scraped=date_scraped,
                                    notes=star_text if has_star else ""
                                )
                                treatment_key = (
                                    record["Therapeutic_Area"],
                                    record["Treatment_Name"],
                                    record["Indication"],
                                    record["Phase"],
                                )
                                if treatment_key not in processed_treatments:
                                    treatments.append(record)
                                    processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Galapagos.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Galapagos's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Galapagos script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []


# -----------------------
# Helper: Phase Mapping
# -----------------------
def get_phase_from_width(width_str: str):
    """
    Convert a 'data-width' percentage (e.g., '37.5%') into (phase, progress).
    """
    logging.info(f"Found: {width_str}")
    if not width_str:
        return ("Unknown", 0.0)
    try:
        val = float(width_str.rstrip('%'))  # remove '%' and parse float
    except ValueError:
        return ("Unknown", 0.0)

    # Adjust thresholds as needed:
    if val > 75:
        phase = "Phase 2"
    elif val > 50:
        phase = "Phase 1"
    elif val > 25:
        phase = "IND-enabling"
    else:
        phase = "Discovery"

    return (phase, val)


# -----------------------
# Helper: Create MasterTable Record
# -----------------------
def create_mastertable_record(
    company,
    area,
    subarea,
    product_candidate,
    target_text,
    study_text,
    drug_class,
    indication_text,
    phase_text,
    progress_val,
    date_updated,
    date_scraped,
    notes=""
):
    """
    Helper that creates a MasterTable-like dictionary (mirroring your reference script usage).
    Now includes a 'notes' field for the star note if applicable.
    """

    # 1) Clean each text field prior to generating keys
    therapeutic_area_clean = clean_text(area)
    subarea_clean = clean_text(subarea)
    treatment_name_clean = clean_text(product_candidate)
    indication_clean = clean_text(indication_text)
    target_clean = clean_text(target_text)
    phase_clean = clean_phase(phase_text)  # ensure uniform phase
    study_clean = clean_text(study_text)
    drug_class_clean = clean_text(drug_class)
    notes_clean = clean_text(notes) if notes else ""

    # 2) Prepare multilingual data
    ta_translator = MultilingualData()
    ta_translator.add_translation("en", therapeutic_area_clean)
    ta_collection = MultilingualDataCollection()
    ta_collection.add_data(ta_translator)

    subarea_translator = MultilingualData()
    subarea_translator.add_translation("en", subarea_clean)
    subarea_collection = MultilingualDataCollection()
    subarea_collection.add_data(subarea_translator)

    name_translator = MultilingualData()
    name_translator.add_translation("en", treatment_name_clean)
    name_collection = MultilingualDataCollection()
    name_collection.add_data(name_translator)

    indication_translator = MultilingualData()
    indication_translator.add_translation("en", indication_clean)
    indication_collection = MultilingualDataCollection()
    indication_collection.add_data(indication_translator)

    target_translator = MultilingualData()
    target_translator.add_translation("en", target_clean)
    target_collection = MultilingualDataCollection()
    target_collection.add_data(target_translator)

    phase_translator = MultilingualData()
    phase_translator.add_translation("en", phase_clean)
    phase_collection = MultilingualDataCollection()
    phase_collection.add_data(phase_translator)

    study_translator = MultilingualData()
    study_translator.add_translation("en", study_clean)
    study_collection = MultilingualDataCollection()
    study_collection.add_data(study_translator)

    drug_class_translator = MultilingualData()
    drug_class_translator.add_translation("en", drug_class_clean)
    drug_class_collection = MultilingualDataCollection()
    drug_class_collection.add_data(drug_class_translator)

    notes_translator = MultilingualData()
    notes_translator.add_translation("en", notes_clean)
    notes_collection = MultilingualDataCollection()
    notes_collection.add_data(notes_translator)

    date_updated_translator = MultilingualData()
    date_updated_translator.add_translation("en", date_updated or "")
    date_updated_collection = MultilingualDataCollection()
    # Note the correction below: we pass the translator itself (not a function call).
    date_updated_collection.add_data(date_updated_translator)

    # 3) Generate the identification key *after* cleaning text
    identification_key = generate_identification_key(
        company, treatment_name_clean, therapeutic_area_clean, indication_clean
    )

    # 4) Build the MasterTable record
    master_record = MasterTable(
        company_name=company,
        therapeutic_area=ta_collection.get_collection_as_json(),
        treatment_name=name_collection.get_collection_as_json(),
        indication=indication_collection.get_collection_as_json(),
        phase=phase_collection.get_collection_as_json(),
        target=target_collection.get_collection_as_json(),
        date_scraped=date_scraped,
        identification_key=identification_key,
        date_last_changed=date_updated_collection.get_collection_as_json(),
        disease_area=subarea_collection.get_collection_as_json(),
        study=study_collection.get_collection_as_json(),
        type_of_molecule=drug_class_collection.get_collection_as_json(),
        notes=notes_collection.get_collection_as_json()
    )

    return master_record.__dict__
