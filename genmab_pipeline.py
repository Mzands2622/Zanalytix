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
from bs4 import BeautifulSoup
import logging
import re

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_genmab_html():
    """
    Returns the Genmab pipeline URL.
    """
    try:
        url = "https://www.genmab.com/antibody-science/pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Genmab pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_genmab_html(html_content):
    """
    Parses Genmab's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Genmab pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Genmab script returned no HTML content. Please investigate!"
            )
            return []


        soup = BeautifulSoup(html_content, "html.parser")

        # ---------------------
        # Extract Pipeline Entries
        # ---------------------
        heading_el = soup.find("div", class_="piplelinetherapeuticheading")
        therapeutic_area = heading_el.get_text(strip=True) if heading_el else None

        cards = soup.find_all("c-eu_single-pipeline-indication-card")
        pipeline_data = []

        for card in cards:
            phase_el = card.find("span", class_=re.compile("pipelinesinglePhaseHeading"))
            phase = clean_phase(phase_el.get_text(strip=True)) if phase_el else None

            compound_el = card.find("span", class_=re.compile("pipelinesinglecompound"))
            compound = clean_text(compound_el.get_text(strip=True)) if compound_el else None

            tech_el = card.find("lightning-formatted-rich-text", class_=re.compile("pipelinesingletechnology"))
            technology = clean_text(tech_el.get_text(strip=True)) if tech_el else None

            indication_el = card.find("lightning-formatted-rich-text", class_=re.compile("pipelinesingleindication"))
            indication = clean_text(indication_el.get_text(strip=True)) if indication_el else None

            pipeline_data.append({
                "phase": phase,
                "compound": compound,
                "technology": technology,
                "indication": indication,
                "therapeutic_area": clean_text(therapeutic_area) if therapeutic_area else None,
                "date_last_updated": "Pipeline as of Jan 2024"
            })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        # Dictionary to track counts for (compound, technology, indication, therapeutic_area)
        combo_counts = {}

        for entry in pipeline_data:
            phase = entry["phase"]
            compound = entry["compound"]
            technology = entry["technology"]
            indication = entry["indication"]
            area = entry["therapeutic_area"]
            date_updated = entry["date_last_updated"]

            # --- Build a base key that does NOT include phase ---
            base_key = (compound, technology, indication, area)
            
            # If first time seeing this base_key, store 1, but do NOT add "-1" to the name
            if base_key not in combo_counts:
                combo_counts[base_key] = 1
                unique_compound_id = compound  # no suffix for the 1st occurrence
            else:
                # Increment and apply suffix for any duplicates
                combo_counts[base_key] += 1
                suffix = combo_counts[base_key]
                unique_compound_id = f"{compound}-{suffix}"

            # Build the identification key WITHOUT phase, to keep it stable if the phase changes.
            identification_key = generate_identification_key(
                "Genmab",
                unique_compound_id,  # possibly has a -2, -3, etc. if duplicates exist
                area,
                indication,
                technology
            )

            # If you want each phase to be a separate pipeline entry, you can still
            # use phase in the 'treatment_key'.
            treatment_key = (compound, technology, indication, phase, area)

            # Duplicate check for final data row creation
            if treatment_key:
                # Create multilingual data
                technology_trans = MultilingualData()
                technology_trans.add_translation("en", technology)

                indication_trans = MultilingualData()
                indication_trans.add_translation("en", indication)

                area_trans = MultilingualData()
                area_trans.add_translation("en", area)

                name_trans = MultilingualData()
                name_trans.add_translation("en", compound)

                phase_trans = MultilingualData()
                phase_trans.add_translation("en", phase)

                date_updated_trans = MultilingualData()
                date_updated_trans.add_translation("en", date_updated)

                technology_collection = MultilingualDataCollection()
                indication_collection = MultilingualDataCollection()
                area_collection = MultilingualDataCollection()
                name_collection = MultilingualDataCollection()
                phase_collection = MultilingualDataCollection()
                date_updated_collection = MultilingualDataCollection()

                technology_collection.add_data(technology_trans)
                indication_collection.add_data(indication_trans)
                area_collection.add_data(area_trans)
                name_collection.add_data(name_trans)
                phase_collection.add_data(phase_trans)
                date_updated_collection.add_data(date_updated_trans)

                master_record = MasterTable(
                    company_name="Genmab",
                    treatment_name=name_collection.get_collection_as_json(),  # keep official compound name
                    indication=indication_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    # We'll store 'technology' in the 'target' field, 
                    # or rename it if your MasterTable supports a separate field
                    target=technology_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,  # uses conditional suffix for uniqueness
                    date_last_changed=date_updated_collection.get_collection_as_json()
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Genmab.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Genmab's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Genmabs script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []