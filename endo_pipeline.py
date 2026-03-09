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
import re

async def fetch_endo_html():
    """
    Fetches the Endo pipeline URL via Zyte.
    """
    try:
        url = "https://www.endo.com/research-and-development/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Endo HTML: {e}")
        return None

async def process_endo_html(html_content):
    """
    Parses the Endo pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Endo pipeline.")
            send_sms(
                phone_number="9144334333", 
                message="Endo script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        raw_data = []

        # Phase mapping for standardization
        phase_mapping = {
            "phase 1": "Phase 1",
            "phase 1 half": "Phase 1",
            "phase 2": "Phase 2",
            "phase 2 half": "Phase 2",
            "phase 3": "Phase 3",
            "phase 3 half": "Phase 3",
            "regulatory": "Regulatory Review"
        }

        def parse_specialty_section(table_div, section_info):
            """Parse the Specialty Medicines table and return list of entries"""
            section_data = []
            therapeutic_rows = table_div.find_all('div', class_='row-therapeutic')
            
            for trow in therapeutic_rows:
                area_tag = trow.find('h3')
                therapeutic_area = clean_text(area_tag.get_text(strip=True)) if area_tag else "N/A"

                container_compounds = trow.find_all('div', class_='container-compound')
                for ccontainer in container_compounds:
                    row_compounds = ccontainer.find_all('div', class_='row-compound')
                    for rcompound in row_compounds:
                        compound_name_tag = rcompound.find('h4')
                        compound_name = clean_text(compound_name_tag.get_text(strip=True)) if compound_name_tag else ""

                        container_indication = rcompound.find('div', class_='container-indication')
                        if not container_indication:
                            continue

                        row_inds = container_indication.find_all(
                            'div', class_='row-indication', attrs={"data-phase": True}
                        )

                        for rind in row_inds:
                            indication_name_tag = rind.find('p', class_='indication-name')
                            indication_name = clean_text(indication_name_tag.get_text(strip=True)) if indication_name_tag else ""
                            
                            raw_phase = rind.get("data-phase", "").lower()
                            phase = phase_mapping.get(raw_phase, "N/A")

                            entry = {
                                "disease_area": section_info["disease_area"],
                                "notes": section_info["notes"],
                                "date_last_changed": section_info["date_last_changed"],
                                "therapeutic_area": therapeutic_area,
                                "treatment_name": compound_name,
                                "indication": indication_name,
                                "phase": phase
                            }
                            section_data.append(entry)
            return section_data

        def parse_general_products_section(header, section_name):
            """Parse sections that use the tableBlockProductsGeneral structure"""
            small_richtext_divs = header.find_all_next(
                'div', class_='block-rich-text font-size-x-small'
            )
            
            section_info = {
                "disease_area": section_name,
                "notes": "N/A",
                "therapeutic_area": "N/A",
                "treatment_name": "N/A",
                "indication": "N/A",
                "phase": "N/A"
            }
            
            # Handle both disclaimer and date if present
            if len(small_richtext_divs) >= 2:
                section_info["notes"] = clean_text(small_richtext_divs[0].get_text(strip=True))
                section_info["date_last_changed"] = clean_text(small_richtext_divs[1].get_text(strip=True))
            elif len(small_richtext_divs) == 1:
                section_info["date_last_changed"] = clean_text(small_richtext_divs[0].get_text(strip=True))

            table = header.find_next(
                "div",
                attrs={"data-content-element-type-alias": "tableBlockProductsGeneral"}
            )

            if table:
                chart_container = table.find('div', class_='product-chart')
                if chart_container:
                    header_tag = chart_container.find('h3', class_='table-header')
                    if header_tag:
                        products_count = re.search(r'(\d+)\s+Products', header_tag.text)
                        if products_count:
                            section_info['products_count'] = int(products_count.group(1))

                    chart_bar = chart_container.find('div', class_='table-chart-bar')
                    if chart_bar and 'style' in chart_bar.attrs:
                        gradient_match = re.search(r'(\d+)%', chart_bar['style'])
                        if gradient_match:
                            rd_percentage = int(gradient_match.group(1))
                            section_info['research_development_percentage'] = rd_percentage
                            section_info['regulatory_submission_percentage'] = 100 - rd_percentage

            return section_info

        # Find all main section headers
        section_headers = soup.find_all(['h3'], class_=['block-header font-size-medium-large']) + \
                        soup.find_all('h3', string=re.compile(r"(Specialty Medicines|Sterile Injectables)", re.IGNORECASE))
        
        for header in section_headers:
            section_name = clean_text(header.get_text(strip=True))
            
            # Check the type of table that follows
            next_table = header.find_next("div", attrs={"data-content-element-type-alias": True})
            if not next_table:
                continue
                
            table_type = next_table.get('data-content-element-type-alias', '')
            
            if table_type == 'tableBlockSpecialtyMedicines':
                # Handle Specialty Medicines section
                small_richtext_divs = header.find_all_next(
                    'div', class_='block-rich-text font-size-x-small'
                )
                if len(small_richtext_divs) >= 2:
                    section_info = {
                        "disease_area": section_name,
                        "notes": clean_text(small_richtext_divs[0].get_text(strip=True)),
                        "date_last_changed": clean_text(small_richtext_divs[1].get_text(strip=True))
                    }
                    specialty_data = parse_specialty_section(next_table, section_info)
                    raw_data.extend(specialty_data)
                    
            elif table_type == 'tableBlockProductsGeneral':
                # Handle general products sections
                section_data = parse_general_products_section(header, section_name)
                raw_data.append(section_data)

        # Create master records for all collected data
        treatments = []
        processed_treatments = set()
        
        for entry in raw_data:
            # Create unique key for deduplication
            treatment_key = (
                entry.get("therapeutic_area", "N/A"),
                entry.get("treatment_name", "N/A"),
                entry.get("indication", "N/A"),
                entry.get("phase", "N/A"),
                entry.get("disease_area", "N/A")
            )

            if treatment_key not in processed_treatments:
                # Generate identification key
                identification_key = generate_identification_key(
                    "Endo",
                    entry["disease_area"],
                    entry.get("indication", "N/A")
                )

                # Create multilingual data objects
                collections = {}
                for field in [
                    "disease_area", "therapeutic_area", "treatment_name", "indication", 
                    "phase", "notes", "research_development_percentage", 
                    "regulatory_submission_percentage"
                ]:
                    translator = MultilingualData()
                    translator.add_translation("en", entry.get(field, "N/A"))
                    collection = MultilingualDataCollection()
                    collection.add_data(translator)
                    collections[field] = collection.get_collection_as_json()

                master_record = MasterTable(
                    company_name="Endo",
                    disease_area=collections["disease_area"],
                    therapeutic_area=collections["therapeutic_area"],
                    treatment_name=collections["treatment_name"],
                    indication=collections["indication"],
                    phase=collections["phase"],
                    date_scraped=datetime.now(timezone.utc),
                    date_last_changed=entry["date_last_changed"],
                    identification_key=identification_key,
                    notes=collections["notes"],
                    research_development_percentage=collections["research_development_percentage"],
                    regulatory_submission_percentage=collections["regulatory_submission_percentage"]
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} entries for Endo.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Endo's Pipeline: {e}")
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Endo script: {e}. Please investigate!"
        )
        return []