from function_app import (
    fetch_with_zyte,
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

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_galderma_html():
    """
    Returns the Galderma pipeline URL.
    """
    try:
        url = "https://www.galderma.com/us/bringing-innovation-life"
        return url
    except Exception as e:
        logging.error(f"Error fetching Galderma pipeline URL: {e}")
        return None

# -----------------------
# Process HTML Function
# -----------------------
async def process_galderma_html(html_content):
    """
    Parses Galderma's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Galderma pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Galderma script returned no HTML content. Please investigate!"
            )
            return []


        soup = BeautifulSoup(html_content, "html.parser")

        final_data = []

        all_h3 = soup.find_all("h3")
        found_projects_header = False
        for h3_el in all_h3:
            text = h3_el.get_text(strip=True).upper()
            if "CURRENT PROJECTS INCLUDE" in text:
                found_projects_header = True
                continue

            if found_projects_header:
                project_name = clean_text(h3_el.get_text(strip=True))

                project_description = ""
                current_tag = h3_el
                while current_tag:
                    current_tag = current_tag.next_sibling
                    if not current_tag:
                        break
                    if current_tag.name == "p":
                        desc_text = clean_text(current_tag.get_text(strip=True))
                        if desc_text:
                            project_description = desc_text
                            break

                if project_description == "":
                    break

                final_data.append({
                    "project_name": project_name,
                    "more_info": project_description
                })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in final_data:
            project_name = clean_text(entry["project_name"])
            more_info = clean_text(entry["more_info"])

            identification_key = generate_identification_key("Galderma", project_name)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)
            info_collection = MultilingualDataCollection()
            info_collection.add_data(info_trans)

            name_trans = MultilingualData()
            name_trans.add_translation("en", project_name)
            name_collection = MultilingualDataCollection()
            name_collection.add_data(name_trans)


            treatment_key = (project_name, more_info)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Galderma",
                    treatment_name=name_collection.get_collection_as_json(),
                    notes=info_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} projects for Galderma.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Galderma's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Galderma script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []