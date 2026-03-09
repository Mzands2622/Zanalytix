from function_app import (
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
import requests

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_regeneron_html():
    """
    Fetches the Regeneron pipeline HTML.
    """
    try:
        url = "https://www.regeneron.com/science/investigational-pipeline"
        return url
        
    except Exception as e:
        logging.error(f"Error fetching Regeneron pipeline HTML: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_regeneron_html(html_content):
    """
    Parses the Regeneron pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Regeneron pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Regeneron script returned no HTML content. Please investigate!"
            )
            return []
        
        url = "https://www.regeneron.com/science/investigational-pipeline"
        response = requests.get(url)
        response.raise_for_status()
        
        # Convert bytes to string using utf-8 encoding
        html_content = response.content.decode('utf-8')
            
        soup = BeautifulSoup(html_content, "html.parser")
        treatments = []
        processed_treatments = set()

        # Dictionary to track how many times each (molecule_name, therapeutic_area, indication, target) appears
        molecule_counts = {}

        # Extract last updated date
        sections = soup.find_all("section")
        last_updated = "Pipeline last updated information not found"
        if len(sections) >= 4:
            target_section = sections[3]
            update_element = target_section.find(
                'p',
                string=lambda text: "last updated" in text.lower() if text else False
            )
            if update_element:
                last_updated = update_element.text.strip()

        # -----------------------------------------------------------
        # Dynamically find all phase buttons & their corresponding div
        # -----------------------------------------------------------
        phase_buttons = soup.find_all("button", {"data-bs-toggle": "collapse"})
        for button in phase_buttons:
            try:
                # Example HTML structure:
                # <button class="accordion-button collapsed"
                #         data-bs-toggle="collapse"
                #         data-bs-target="#flush-collapse-Phase1" 
                # >
                #     <span>Phase 1</span>
                # </button>
                
                # 1) Extract the text from <span> (e.g. "Phase 1")
                span = button.find("span")
                if not span:
                    continue
                phase_name_raw = span.get_text(strip=True)  # e.g. "Phase 1"
                
                # 2) "Clean" phase (if desired)
                phase_name = clean_phase(phase_name_raw)
                
                # 3) Extract the data-bs-target (e.g. "#flush-collapse-Phase1")
                data_target = button.get("data-bs-target", "")
                if not data_target.startswith("#"):
                    continue
                # Remove the '#' prefix
                target_id = data_target[1:]  # e.g. "flush-collapse-Phase1"
                
                # 4) Find the <div> with this ID
                phase_div = soup.find("div", id=target_id)
                if not phase_div:
                    continue
                
                # ------------------------------------------------
                # Now parse the "entries" under this phase's <div>
                # ------------------------------------------------
                entries = phase_div.find_all("div", class_="pipeline-table-entry")
                for entry in entries:
                    try:
                        # Extract and clean fields
                        molecule_name = clean_text(
                            entry.find("div", class_="pipeline-table-entry-name").text.strip()
                        )
                        therapeutic_area = clean_text(
                            entry.find("div", class_="pipeline-table-entry-therapeuticArea-text").text.strip()
                        )
                        modality = clean_text(
                            entry.find("div", class_="pipeline-table-entry-modality").text.strip()
                        )
                        indication = clean_text(
                            entry.find("div", class_="pipeline-table-entry-indication").text.strip()
                        )
                        target = clean_text(
                            entry.find("div", class_="pipeline-table-entry-target").text.strip()
                        )

                        # Build a base key that does NOT include phase
                        base_key = (molecule_name, therapeutic_area, indication, target)

                        # -------------------------
                        # Conditional Counter Logic
                        # -------------------------
                        if base_key not in molecule_counts:
                            # first occurrence => keep name as-is
                            molecule_counts[base_key] = 1
                            unique_id_molecule = molecule_name
                        else:
                            # subsequent duplicates => append suffix
                            molecule_counts[base_key] += 1
                            suffix_val = molecule_counts[base_key]
                            unique_id_molecule = f"{molecule_name}-{suffix_val}"

                        # Now build the identification key (excluding phase)
                        identification_key = generate_identification_key(
                            "Regeneron",
                            unique_id_molecule,  
                            therapeutic_area,
                            indication,
                            target
                        )

                        date_scraped = datetime.now(timezone.utc)
                        # Use phase in the "treatment_key" if you want separate records for each phase
                        treatment_key = (
                            molecule_name,
                            indication,
                            phase_name,
                            therapeutic_area,
                            modality,
                            target
                        )

                        # Setup multilingual data
                        indication_translator = MultilingualData()
                        therapeutic_area_translator = MultilingualData()
                        target_translator = MultilingualData()
                        modality_translator = MultilingualData()
                        name_translator = MultilingualData()
                        phase_translator = MultilingualData()
                        date_updated_translator = MultilingualData()

                        indication_translator.add_translation('en', indication)
                        therapeutic_area_translator.add_translation('en', therapeutic_area)
                        target_translator.add_translation('en', target)
                        modality_translator.add_translation('en', modality)
                        name_translator.add_translation("en", molecule_name)
                        phase_translator.add_translation("en", phase_name)
                        date_updated_translator.add_translation("en", last_updated)

                        indication_collection = MultilingualDataCollection()
                        therapeutic_area_collection = MultilingualDataCollection()
                        target_collection = MultilingualDataCollection()
                        modality_collection = MultilingualDataCollection()
                        name_collection = MultilingualDataCollection()
                        phase_collection = MultilingualDataCollection()
                        date_updated_collection = MultilingualDataCollection()

                        indication_collection.add_data(indication_translator)
                        therapeutic_area_collection.add_data(therapeutic_area_translator)
                        target_collection.add_data(target_translator)
                        modality_collection.add_data(modality_translator)
                        name_collection.add_data(name_translator)
                        phase_collection.add_data(phase_translator)
                        date_updated_collection.add_data(date_updated_translator)


                        # Create master record if not a duplicate by (molecule, indication, phase, etc.)
                        if treatment_key not in processed_treatments:
                            master_record = MasterTable(
                                company_name="Regeneron",
                                treatment_name=name_collection.get_collection_as_json(),  # official name stays unchanged
                                indication=indication_collection.get_collection_as_json(),
                                therapeutic_area=therapeutic_area_collection.get_collection_as_json(),
                                phase=phase_collection.get_collection_as_json(),
                                target=target_collection.get_collection_as_json(),
                                modality=modality_collection.get_collection_as_json(),
                                identification_key=identification_key,  # uses conditional suffix
                                date_scraped=date_scraped,
                                date_last_changed=date_updated_collection.get_collection_as_json()
                            )
                            treatments.append(master_record.__dict__)
                            processed_treatments.add(treatment_key)

                    except Exception as e:
                        logging.error(
                            f"Error processing entry under {phase_name}: {e}",
                            exc_info=True
                        )
            except Exception as e:
                logging.error(f"Error processing phase button: {e}", exc_info=True)

        logging.info(f"Processed {len(treatments)} treatments for Regeneron.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Regeneron's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Regeneron script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []

