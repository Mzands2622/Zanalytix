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
from urllib.parse import urljoin


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_acadia_html():
    """
    Returns the Acadia pipeline URL.
    """
    try:
        url = "https://acadia.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Acadia pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_acadia_html(html_content):
    """
    Parses Acadia's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Acadia pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Acadia script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        results = []

        pipeline_items = soup.select("div.clickable.pipeline")

        for item in pipeline_items:
            header = item.select_one("header")
            drug_name_raw = header.select_one("p.product").get_text(strip=True) if header.select_one("p.product") else None

            # Splitting drug_name into brand_name and generic_name
            brand_name = None
            generic_name = None
            if drug_name_raw:
                if '(' in drug_name_raw and drug_name_raw.endswith(')'):
                    brand_name, generic_name = drug_name_raw.rsplit('(', 1)
                    brand_name = clean_text(brand_name)
                    generic_name = clean_text(generic_name.strip(')'))

            indication = clean_text(header.select_one("p.subtitle").get_text(strip=True)) if header.select_one("p.subtitle") else None
            phase = clean_phase(header.select_one("p.phase-label.subtitle").get_text(strip=True)) if header.select_one("p.phase-label.subtitle") else None
            approval_year = clean_text(header.select_one("p.year").get_text(strip=True)) if header.select_one("p.year") else None
            approval_type = clean_text(header.select_one("p.approval.subtitle").get_text(strip=True)) if header.select_one("p.approval.subtitle") else None
            description = clean_text(item.select_one("div.description div.rich-text").get_text(strip=True)) if item.select_one("div.description div.rich-text") else None

            # Extracting dialog content (notes)
            dialog_id = item.select_one("a.dialog-button")["data-dialog"] if item.select_one("a.dialog-button") else None
            notes = ""

            if dialog_id:
                dialog = soup.find("dialog", {"id": dialog_id})
                if dialog:
                    notes_text = dialog.select_one("div.rich-text").get_text(strip=True) if dialog.select_one("div.rich-text") else ""
                    links = []
                    for a_tag in dialog.select("div.rich-text a"):
                        link_text = a_tag.get_text(strip=True)
                        href = a_tag["href"]
                        full_link = urljoin("https://acadia.com", href)
                        links.append(f"{link_text}: {full_link}")
                    notes = f"{notes_text}\n" + "\n".join(links)
                    notes = clean_text(notes)

            results.append({
                "treatment_name": drug_name_raw,
                "brand_name": brand_name,
                "generic_name": generic_name,
                "indication": indication,
                "phase": phase,
                "approval_year": approval_year,
                "approval_type": approval_type,
                "comment": description,
                "notes": notes,
            })

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in results:
            identification_key = generate_identification_key(
                "Acadia", entry["treatment_name"], entry["indication"], entry["phase"]
            )

            # Create multilingual objects
            indication_trans = MultilingualData()
            indication_trans.add_translation("en", entry["indication"])

            year_trans = MultilingualData()
            year_trans.add_translation("en", entry["approval_year"])

            type_trans = MultilingualData()
            type_trans.add_translation("en", entry["approval_type"])

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", entry["notes"])

            comment_trans = MultilingualData()
            comment_trans.add_translation("en", entry["comment"])

            treatment_name_trans = MultilingualData()
            treatment_name_trans.add_translation("en", entry["treatment_name"])

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", entry["phase"])

            # Collections
            indication_collection = MultilingualDataCollection()
            year_collection = MultilingualDataCollection()
            type_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            comment_collection = MultilingualDataCollection()
            treatment_name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            indication_collection.add_data(indication_trans)
            year_collection.add_data(year_trans)
            type_collection.add_data(type_trans)
            notes_collection.add_data(notes_trans)
            comment_collection.add_data(comment_trans)
            treatment_name_collection.add_data(treatment_name_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (
                entry["treatment_name"],
                entry["indication"],
                entry["phase"],
                entry["approval_year"],
                entry["notes"],
            )

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Acadia Pharmaceuticals",
                    treatment_name=treatment_name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    approval_date=year_collection.get_collection_as_json(),  # Updated
                    approval_type=type_collection.get_collection_as_json(),
                    notes=notes_collection.get_collection_as_json(),
                    comment=comment_collection.get_collection_as_json(),  # Added
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Acadia.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Acadia's Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Acadia script: {e}. Please investigate!"
        )
        return []
