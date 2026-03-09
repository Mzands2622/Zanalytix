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


# -----------------------
# Fetch Base URL Function
# -----------------------
async def fetch_aurobindousa_html():
    """
    Returns the base URL for Aurobindo pipeline.
    """
    try:
        url = 'https://www.aurobindousa.com/v2/product-catalog/?sf_paged=1'
        return url
    except Exception as e:
        logging.error(f"Error fetching Aurobindo pipeline HTML: {e}")
        return None


# -----------------------
# Fetch All Pages Function
# -----------------------
async def fetch_all_pages_aurobindousa(html_content):
    """
    Handles pagination and combines HTML for all pages.
    """
    try:
        base_url = 'https://www.aurobindousa.com/v2/product-catalog/?sf_paged='
        current_page = 2
        complete_html = html_content

        while True:
            page_url = f"{base_url}{current_page}"
            logging.info(f"Fetching page: {page_url}")

            new_html_content = await fetch_with_zyte(page_url)
            if not new_html_content:
                logging.error(f"Failed to fetch HTML content from page {current_page}.")
                break

            complete_html += new_html_content

            soup = BeautifulSoup(new_html_content, 'html.parser')
            next_page_link = soup.select_one('.pagination .nav-previous a')

            if not next_page_link:
                break

            current_page += 1

        logging.info("Successfully fetched HTML content for all pages.")
        return complete_html

    except Exception as e:
        logging.error(f"Error during pagination: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_aurobindousa_html(html_content):
    """
    Parses the HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.error("No HTML content to process for Aurobindo pipeline.")
            return []

        complete_html = await fetch_all_pages_aurobindousa(html_content)
        if not complete_html:
            logging.error("Failed to fetch all paginated HTML content.")
            return []

        treatments = []
        processed_treatments = set()

        all_treatments = parse_treatments_aurobindousa(complete_html)

        for treatment in all_treatments:
            try:
                product_name = clean_text(treatment.get("Product_Name", "Unknown"))
                brand = clean_text(treatment.get("Brand", "Unknown"))
                therapeutic_class = clean_text(treatment.get("Therapeutic_Class", "Unknown"))
                ndc = clean_text(treatment.get("NDC", "Unknown"))
                strength = clean_text(treatment.get("Strength", "Unknown"))
                size = clean_text(treatment.get("Size", "Unknown"))
                form = clean_text(treatment.get("Form", "Unknown"))

                identification_key = generate_identification_key("Aurobindo", product_name, therapeutic_class)
                date_scraped = datetime.now(timezone.utc)
                treatment_key = (product_name, brand, therapeutic_class, ndc)

                therapeutic_class_translator = MultilingualData()
                form_translator = MultilingualData()

                therapeutic_class_translator.add_translation("en", therapeutic_class)
                form_translator.add_translation("en", form)

                therapeutic_class_collection = MultilingualDataCollection()
                form_collection = MultilingualDataCollection()

                therapeutic_class_collection.add_data(therapeutic_class_translator)
                form_collection.add_data(form_translator)

                if treatment_key not in processed_treatments:
                    master_record = MasterTable(
                        company_name="Aurobindo",
                        treatment_name=product_name,
                        therapeutic_area=therapeutic_class_collection.get_collection_as_json(),
                        strength=strength,
                        size=size,
                        modality=form_collection.get_collection_as_json(),
                        identification_key=identification_key,
                        date_scraped=date_scraped,
                        brand_name=brand,
                        ndc=ndc
                    )
                    treatments.append(master_record.__dict__)
                    processed_treatments.add(treatment_key)

            except Exception as e:
                logging.error(f"Error processing treatment {product_name if 'product_name' in locals() else 'unknown'}: {e}")
                continue

        logging.info(f"Processed {len(treatments)} treatments for Aurobindo.")
        return treatments

    except Exception as e:
        logging.error(f"Error during processing: {e}")
        return []


# -----------------------
# Parse Treatments Function
# -----------------------
def parse_treatments_aurobindousa(html):
    soup = BeautifulSoup(html, 'html.parser')
    treatments = []
    rows = soup.select("table.table tbody tr")

    for row in rows:
        try:
            cells = row.find_all("td")
            treatments.append({
                "Product_Name": cells[0].get_text(strip=True),
                "Brand": cells[1].get_text(strip=True),
                "Therapeutic_Class": cells[2].get_text(strip=True),
                "NDC": cells[3].get_text(strip=True),
                "Strength": cells[4].get_text(strip=True),
                "Size": cells[5].get_text(strip=True),
                "Form": cells[6].get_text(strip=True),
            })
        except Exception as e:
            logging.error(f"Error parsing row: {e}")
            continue

    return treatments
