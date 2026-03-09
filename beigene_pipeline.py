from function_app import (
    fetch_with_zyte,
    clean_text,                # Ensure you have a clean_text function available
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
import json

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_beigene_html():
    """
    Returns the Beigene pipeline URL.
    """
    try:
        url = "https://www.beigene.com/science/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Beigene pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_beigene_html(html_content):
    """
    Parses Beigene's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for BeiGene pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="BeiGene script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # --- 1) Parse Sup Explanations ---
        sup_explanations = {}
        footnote_containers = soup.select("div.wp-block-group__inner-container")

        for container in footnote_containers:
            paragraphs = container.find_all('p', class_="has-small-font-size")
            for paragraph in paragraphs:
                footnote_parts = paragraph.decode_contents().split('<br/>')
                for part in footnote_parts:
                    part_soup = BeautifulSoup(part, 'html.parser')
                    sup_tag = part_soup.find('sup')
                    if sup_tag:
                        sup_text = sup_tag.get_text(strip=True)
                        sup_tag.extract()
                        explanation = part_soup.get_text(strip=True)
                        if explanation:
                            sup_explanations[sup_text] = explanation

        logging.info(f"Parsed {len(sup_explanations)} sup explanations.")

        # --- 3) Scrape each \"Therapeutic Area\" block ---
        pipeline_programs = soup.select("div.pipeline__program")
        for program in pipeline_programs:
            # Extract Therapeutic Area from the header
            header_tag = program.select_one("div.pipeline__program-header h2")
            if not header_tag:
                logging.warning("Therapeutic Area header not found.")
                continue

            # Clean the text for the therapeutic area right away
            therapeutic_area = clean_text(
                header_tag.get_text(strip=True).replace("Development Programs – ", "")
            )

            # Extract all entries within the pipeline
            pipeline_entries = program.select("div.pipeline > div")

            # Initialize variables to track the current drug
            current_drug = {}
            for entry in pipeline_entries:
                # Check if the entry is a drug name
                drug_name_tag = entry.find("h3", class_="drug-name")
                if drug_name_tag:
                    # If there's an existing drug, process its indications and phases
                    if current_drug:
                        indications = current_drug.get("indications", [])
                        phases = current_drug.get("phases", [])

                        # Ensure indications and phases lists are of the same length
                        if len(indications) != len(phases):
                            logging.warning(
                                f"Number of indications ({len(indications)}) and phases ({len(phases)}) "
                                f"do not match for product '{current_drug.get('product_name')}'. "
                                f"Truncating to minimum length."
                            )
                            min_length = min(len(indications), len(phases))
                            indications = indications[:min_length]
                            phases = phases[:min_length]

                        # Create separate entries for each Indication-Phase pair
                        for indication_tuple, phase_text in zip(indications, phases):
                            # Clean the phase
                            phase_clean = clean_phase(phase_text)
                            # Indication text + sup
                            indication_text, sup = indication_tuple
                            # If sup is empty, fallback to any sup on the main drug
                            sup_final = sup if sup else current_drug.get("sup", "")
                            sup_explanation = (
                                sup_explanations.get(sup_final, "") if sup_final else ""
                            )

                            # Clean all relevant text fields prior to key generation
                            drug_cln = clean_text(current_drug.get("product_name", ""))
                            indication_cln = clean_text(indication_text)
                            molecule_cln = clean_text(current_drug.get("molecule", ""))
                            notes_cln = clean_text(sup_explanation)
                            # We'll also store the area & phase in cleaned form
                            area_cln = clean_text(current_drug.get("therapeutic_area", ""))
                            phase_cln = clean_phase(phase_clean)

                            # Generate a unique identification key
                            identification_key = generate_identification_key(
                                "Beigene",
                                drug_cln,
                                indication_cln,
                                molecule_cln,
                                notes_cln
                            )

                            # Build multilingual data for each field
                            area_trans = MultilingualData()
                            area_trans.add_translation("en", area_cln)

                            program_trans = MultilingualData()
                            program_trans.add_translation("en", drug_cln)

                            indication_trans = MultilingualData()
                            indication_trans.add_translation("en", indication_cln)

                            molecule_trans = MultilingualData()
                            molecule_trans.add_translation("en", molecule_cln)

                            notes_trans = MultilingualData()
                            notes_trans.add_translation("en", notes_cln)

                            phase_trans = MultilingualData()
                            phase_trans.add_translation("en", phase_cln)

                            # Wrap them in collections
                            area_collection = MultilingualDataCollection()
                            program_collection = MultilingualDataCollection()
                            indication_collection = MultilingualDataCollection()
                            molecule_collection = MultilingualDataCollection()
                            notes_collection = MultilingualDataCollection()
                            phase_collection_mc = MultilingualDataCollection()  # rename to avoid shadowing

                            area_collection.add_data(area_trans)
                            program_collection.add_data(program_trans)
                            indication_collection.add_data(indication_trans)
                            molecule_collection.add_data(molecule_trans)
                            notes_collection.add_data(notes_trans)
                            phase_collection_mc.add_data(phase_trans)

                            # Prepare a record key to avoid duplicates
                            record_key = (
                                area_cln,
                                drug_cln,
                                molecule_cln,
                                indication_cln,
                                phase_cln,
                                sup_final
                            )

                            if record_key not in processed_treatments:
                                # Build MasterTable object
                                master_record = MasterTable(
                                    company_name="BeiGene",
                                    treatment_name=program_collection.get_collection_as_json(),
                                    indication=indication_collection.get_collection_as_json(),
                                    therapeutic_area=area_collection.get_collection_as_json(),
                                    phase=phase_collection_mc.get_collection_as_json(),
                                    target=molecule_collection.get_collection_as_json(),
                                    date_scraped=date_scraped,
                                    identification_key=identification_key,
                                    notes=notes_collection.get_collection_as_json(),
                                )
                                treatments.append(master_record.__dict__)
                                processed_treatments.add(record_key)

                        # Reset current_drug
                        current_drug = {}

                    # Extract drug name
                    product_name_raw = drug_name_tag.get_text(strip=True)
                    product_name_clean = clean_text(product_name_raw)
                    # Extract sup if exists
                    sup_tag = drug_name_tag.find('sup')
                    sup_val = sup_tag.get_text(strip=True) if sup_tag else ""

                    # Extract molecule from the subheading
                    molecule_tag = entry.find("span", class_="drug-subheading")
                    if molecule_tag:
                        molecule_raw = molecule_tag.get_text(strip=True)
                        # e.g. removing parentheses
                        molecule_clean = clean_text(
                            molecule_raw.replace("(", "").replace(")", "")
                        )
                    else:
                        molecule_clean = ""

                    # Initialize the current drug dictionary
                    current_drug = {
                        "therapeutic_area": therapeutic_area,
                        "product_name": product_name_clean,
                        "molecule": molecule_clean,
                        "indications": [],
                        "phases": [],
                        "sup": sup_val,  # Add sup key from drug name
                    }

                # Check if the entry is an indication
                elif "indication" in entry.get("class", []):
                    indication_html = entry.decode_contents()
                    indication_soup = BeautifulSoup(indication_html, 'html.parser')
                    sup_tag = indication_soup.find('sup')
                    if sup_tag:
                        sup_val = sup_tag.get_text(strip=True)
                        sup_tag.extract()
                        indication_text = indication_soup.get_text(strip=True)
                    else:
                        # Check for '†' or other symbols at the end
                        indication_text_full = indication_soup.get_text(strip=True)
                        sup_match = re.search(r'(†)$', indication_text_full)
                        if sup_match:
                            sup_val = sup_match.group(1)
                            indication_text = indication_text_full.replace(sup_val, '').strip(", ")
                        else:
                            sup_val = ''
                            indication_text = indication_text_full

                    # We'll clean them later when generating final records
                    current_drug["indications"].append((indication_text, sup_val))

                # Check if the entry is a phase
                elif "phase" in entry.get("class", []):
                    phase_classes = entry.get("class", [])
                    phase_val = "unknown"
                    for possible_phase in ["phase-1", "phase-2", "phase-3"]:
                        if possible_phase in phase_classes:
                            phase_val = possible_phase.replace("phase-", "Phase ")
                            break
                    current_drug["phases"].append(phase_val)

                # We ignore other entries like <hr> or empty divs

        # Append the last drug's data after the loop (if any remains)
        if current_drug:
            indications = current_drug.get("indications", [])
            phases = current_drug.get("phases", [])
            sup_from_drug = current_drug.get("sup", "")

            # Ensure indications and phases lists are of the same length
            if len(indications) != len(phases):
                logging.warning(
                    f"Number of indications ({len(indications)}) and phases ({len(phases)}) "
                    f"do not match for product '{current_drug.get('product_name')}'. "
                    f"Truncating to minimum length."
                )
                min_length = min(len(indications), len(phases))
                indications = indications[:min_length]
                phases = phases[:min_length]

            # Create separate entries for each Indication-Phase pair
            for indication_tuple, phase_text in zip(indications, phases):
                # Clean up the phase
                phase_clean = clean_phase(phase_text)
                # Indication text + sup
                indication_text, sup_val = indication_tuple
                sup_final = sup_val if sup_val else sup_from_drug
                sup_explanation = (
                    sup_explanations.get(sup_final, "") if sup_final else ""
                )

                # Clean all relevant text fields
                drug_cln = clean_text(current_drug.get("product_name", ""))
                indication_cln = clean_text(indication_text)
                molecule_cln = clean_text(current_drug.get("molecule", ""))
                notes_cln = clean_text(sup_explanation)
                area_cln = clean_text(current_drug.get("therapeutic_area", ""))
                phase_cln = clean_phase(phase_clean)

                # Generate identification key
                identification_key = generate_identification_key(
                    "Beigene",
                    drug_cln,
                    indication_cln,
                    molecule_cln,
                    notes_cln
                )

                # Build multilingual data
                area_trans = MultilingualData()
                area_trans.add_translation("en", area_cln)

                program_trans = MultilingualData()
                program_trans.add_translation("en", drug_cln)

                indication_trans = MultilingualData()
                indication_trans.add_translation("en", indication_cln)

                molecule_trans = MultilingualData()
                molecule_trans.add_translation("en", molecule_cln)

                notes_trans = MultilingualData()
                notes_trans.add_translation("en", notes_cln)

                phase_trans = MultilingualData()
                phase_trans.add_translation("en", phase_cln)

                # Collections
                area_collection = MultilingualDataCollection()
                program_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                molecule_collection = MultilingualDataCollection()
                notes_collection = MultilingualDataCollection()
                phase_collection_mc = MultilingualDataCollection()

                area_collection.add_data(area_trans)
                program_collection.add_data(program_trans)
                indication_collection.add_data(indication_trans)
                molecule_collection.add_data(molecule_trans)
                notes_collection.add_data(notes_trans)
                phase_collection_mc.add_data(phase_trans)

                record_key = (
                    area_cln,
                    drug_cln,
                    molecule_cln,
                    indication_cln,
                    phase_cln,
                    sup_final
                )

                if record_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="BeiGene",
                        treatment_name=program_collection.get_collection_as_json(),
                        indication=indication_collection.get_collection_as_json(),
                        therapeutic_area=area_collection.get_collection_as_json(),
                        phase=phase_collection_mc.get_collection_as_json(),
                        target=molecule_collection.get_collection_as_json(),
                        date_scraped=date_scraped,
                        identification_key=identification_key,
                        notes=notes_collection.get_collection_as_json(),
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(record_key)

        logging.info(f"Processed {len(treatments)} treatments for Beigene.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping BeiGene's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in BeiGene script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []