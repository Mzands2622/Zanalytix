from function_app import (
    fetch_with_zyte,
    clean_text,  # If you have a custom clean_text() available
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
async def fetch_innovent_html():
    """
    Returns the Innovent pipeline URL.
    """
    try:
        url = "https://www.innoventbio.com/ScienceAndProducts/Pipeline"
        return url
    except Exception as e:
        logging.error(f"Error fetching Innovent pipeline URL: {e}")
        return None


# -----------------------
# Process HTML Function
# -----------------------
async def process_innovent_html(html_content):
    """
    Parses Innovent's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Innovent pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Innovent script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # ---------------------
        # Extract Products
        # ---------------------
        products = []
        headers = soup.find_all('div', class_='title font-color-white table-title grey_bg font-color-blue table-row-grey col')

        for header in headers:
            therapeutic_area = header.get_text(strip=True)

            sibling = header.find_parent('div', class_='row table-border-bottom').find_next_sibling()
            while sibling and 'pipeline-ani' in sibling.get('class', []):
                product = {"therapeutic_area": therapeutic_area}

                # Extract Product Details
                name_div = sibling.find('div', class_='product-name')
                if name_div:
                    product['name'] = name_div.get_text(strip=True)

                subtitle_div = name_div.find('div', class_='pipelineSubtitle')
                if subtitle_div:
                    product['generic_name'] = subtitle_div.get_text(strip=True).strip('()')

                target_div = sibling.find('div', class_='target')
                if target_div:
                    product['target'] = target_div.get_text(strip=True)

                # Development Phase
                phases = ['Pre-clinical', 'IND', 'Phase 1', 'Phase 2', 'Phase 3/Pivotal', 'NDA', 'Launched']
                phase_cells = sibling.find_all('span', class_='relative')
                current_phase = None

                for i, cell in enumerate(phase_cells):
                    if 'w-50' in cell.get('class', []) or 'd-none' in cell.get('class', []):
                        current_phase = phases[i] if 'w-50' in cell.get('class', []) else phases[i - 1]
                        break

                if not current_phase and all('d-none' not in cell.get('class', []) for cell in phase_cells):
                    current_phase = 'Launched'

                product['development_phase'] = current_phase

                # Detailed Info
                info_content = sibling.find('div', class_='info-content')
                if info_content:
                    product['detailed_info'] = info_content.get_text(strip=True)

                products.append(product)
                sibling = sibling.find_next_sibling()

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for product in products:
            area = clean_text(product.get("therapeutic_area", ""))
            name = clean_text(product.get("name", ""))
            generic_name = clean_text(product.get("generic_name", ""))
            target = clean_text(product.get("target", ""))
            phase = clean_phase(product.get("development_phase", ""))
            detailed_info = clean_text(product.get("detailed_info", ""))

            identification_key = generate_identification_key("Innovent", name, area, generic_name)

            # Multilingual Data
            area_trans = MultilingualData()
            area_trans.add_translation("en", area)

            name_trans = MultilingualData()
            name_trans.add_translation("en", name)

            generic_name_trans = MultilingualData()
            generic_name_trans.add_translation("en", generic_name)

            target_trans = MultilingualData()
            target_trans.add_translation("en", target)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            detailed_info_trans = MultilingualData()
            detailed_info_trans.add_translation("en", detailed_info)

            # Collections
            area_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            generic_name_collection = MultilingualDataCollection()
            target_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            name_collection.add_data(name_trans)
            generic_name_collection.add_data(generic_name_trans)
            target_collection.add_data(target_trans)
            notes_collection.add_data(detailed_info_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (area, name, generic_name, target, phase, detailed_info)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Innovent",
                    treatment_name=name_collection.get_collection_as_json(),
                    generic_name=generic_name_collection.get_collection_as_json(),
                    therapeutic_area=area_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    target=target_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key,
                    notes=notes_collection.get_collection_as_json()
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Innovent.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Innovent's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Innovent script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []
