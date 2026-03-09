import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Assuming these imports pull in your needed functions/classes:
# - fetch_with_zyte
# - clean_text
# - clean_phase
# - MasterTable (needs to have a "country" field)
# - MultilingualData
# - MultilingualDataCollection
# - generate_identification_key
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


# --------------------------------------------------------
# 1) FETCH HTML FUNCTION
# --------------------------------------------------------
async def fetch_kamada_html():
    """
    Returns the Kamada pipeline URL. 
    (You might already be fetching the HTML with fetch_with_zyte or something similar.)
    """
    try:
        url = "https://www.kamada.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Kamada pipeline URL: {e}")
        return None


# --------------------------------------------------------
# 2) PROCESS HTML FUNCTION
# --------------------------------------------------------
async def process_kamada_html(html_content):
    """
    Parses Kamada's pipeline HTML and returns a list of serialized MasterTable objects.
    Includes logic to extract 'Country' from the phase text (EU/US).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Kamada pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Kamada script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        pipeline_data = []
        pipeline_items = soup.find_all("div", class_="pipelineItem")
        treatment_count = 0

        # --------------------------------------------------------
        # Extract relevant data from HTML
        # --------------------------------------------------------
        for item in pipeline_items:
            # Treatment name
            title_tag = item.find("h2")
            treatment_name = clean_text(title_tag.get_text(strip=True)) if title_tag else None

            therapeutic_area = None
            partner = None
            notes_list = []

            # Additional info in "pipelineExtras"
            extras_div = item.find("div", class_="pipelineExtras")
            if extras_div:
                all_p = extras_div.find_all("p", attrs={"data-wahfont": True})
                for p_tag in all_p:
                    text = clean_text(p_tag.get_text(strip=True))
                    if "Therapeutic Area:" in text:
                        therapeutic_area = text.replace("Therapeutic Area:", "").strip()
                    else:
                        # Heuristic to catch partner or collaboration references
                        if "partner" in text.lower() or "collaborat" in text.lower():
                            partner = text
                        elif text:
                            notes_list.append(text)

            # The pipeline "progress" sections
            progress_wrappers = (
                item.find_all("div", class_="pipelineProgressWrapper") +
                item.find_all("div", class_="pipelineProgressWrapper2")
            )

            # Potential "more info" text in "pipelineDesc"
            more_info = None
            pipeline_desc_div = item.find("div", class_="pipelineDesc")
            if pipeline_desc_div:
                desc_texts = [
                    clean_text(p_tag.get_text(strip=True))
                    for p_tag in pipeline_desc_div.find_all("p", attrs={"data-wahfont": True})
                ]
                if desc_texts:
                    more_info = "\n".join(desc_texts)

            # Clean up partner text
            if partner:
                partner = (
                    partner.replace("Partnered with", "")
                           .replace("In collaboration with", "")
                           .strip()
                )

            # Build data for each progress item
            if progress_wrappers:
                for pw in progress_wrappers:
                    progress_div = pw.find("div", class_="pipelineProgress")
                    if progress_div:
                        stage_text = clean_phase(progress_div.get_text(strip=True))
                        data_item = {
                            "Treatment Name": treatment_name,
                            "Therapeutic Area": therapeutic_area,
                            "Development Stage": stage_text
                        }
                        if partner:
                            data_item["Partner or Sponsor"] = partner
                        if notes_list:
                            data_item["Notes"] = notes_list
                        if more_info:
                            data_item["More Info"] = more_info
                        pipeline_data.append(data_item)
            else:
                # No progress wrappers found
                data_item = {
                    "Treatment Name": treatment_name,
                    "Therapeutic Area": therapeutic_area,
                    "Development Stage": None
                }
                if partner:
                    data_item["Partner or Sponsor"] = partner
                if notes_list:
                    data_item["Notes"] = notes_list
                if more_info:
                    data_item["More Info"] = more_info
                pipeline_data.append(data_item)

        # --------------------------------------------------------
        # Convert extracted data into MasterTable objects
        # --------------------------------------------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            treatment_name = clean_text(entry.get("Treatment Name", "Unknown"))
            therapeutic_area = clean_text(entry.get("Therapeutic Area", "Unknown"))
            development_stage = clean_phase(entry.get("Development Stage", "Unknown"))
            partner = clean_text(entry.get("Partner or Sponsor", "Unknown"))
            notes = "; ".join(entry.get("Notes", []))
            notes = clean_text(notes)
            more_info = clean_text(entry.get("More Info", ""))

            # ------------------------------------------------
            # NEW: Extract country info from development_stage
            # ------------------------------------------------
            country_str = ""
            phase_lower = development_stage.lower() if development_stage else ""

            # Check for EU
            if "eu" in phase_lower:
                country_str += "EU"

            # Check for US or FDA
            if "us" in phase_lower or "fda" in phase_lower:
                # If country_str isn't empty, add a separator before appending
                if country_str:
                    country_str += ", "
                country_str += "US"

            # Build an identification key for the record
            identification_key = generate_identification_key(
                "Kamada",
                treatment_name,
                therapeutic_area,
                country_str
            )
            treatment_count += 1

            # Create MultilingualData objects
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", partner)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)

            # NEW: country multilingual data
            country_trans = MultilingualData()
            country_trans.add_translation("en", country_str)

            name_trans = MultilingualData()
            name_trans.add_translation("en", treatment_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", development_stage)

            # Collections
            area_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            info_collection = MultilingualDataCollection()
            country_collection = MultilingualDataCollection()  # <--- NEW
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            # Add data to each collection
            area_collection.add_data(area_trans)
            partner_collection.add_data(partner_trans)
            notes_collection.add_data(notes_trans)
            info_collection.add_data(info_trans)
            country_collection.add_data(country_trans)  # <--- NEW
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)

            # Use a tuple to ensure we don't insert duplicates
            treatment_key = (
                treatment_name,
                therapeutic_area,
                development_stage,
                partner,
                notes,
                more_info
            )

            if treatment_key not in processed_treatments:
                # Create the final record
                master_record = MasterTable(
                    company_name="Kamada Pharmaceuticals",
                    treatment_name=name_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    country=country_collection.get_collection_as_json()  # <--- Add country here
                )

                # Convert to dict and add to results
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Kamada.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Kamada's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Kamada script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []