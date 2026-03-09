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

# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_zealand_html():
    """
    Returns the Zealand Pharma pipeline URL (or handles any error/logging).
    """
    try:
        url = "https://www.zealandpharma.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Zealand pipeline URL: {e}")
        return None

# -----------------------
# Process HTML Function
# -----------------------
async def process_zealand_html(html_content):
    """
    Parses Zealand Pharma's pipeline HTML and returns a list of serialized MasterTable objects,
    with multilingual data collections for:
      - therapeutic_area
      - treatment_name
      - phase
      - partners
      - partner_images
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Zealand pipeline.")
            send_sms(
                phone_number="9144334333", 
                message="Zealand script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # --------------------------------------
        # 1) SCRAPE LOGIC (build raw dicts)
        # --------------------------------------
        accordion_items = soup.find_all('div', class_='accordion__item')
        pipeline_data = []  # List of dicts, one per treatment

        for item in accordion_items:
            # Therapeutic Area
            cat_header = item.find('div', class_='pipeTable__cat')
            if not cat_header:
                continue
            therapeutic_area = cat_header.get_text(strip=True)

            # Rows for each treatment
            rows = item.find_all('div', class_='pipeTable__row')
            for row in rows:
                # Treatment Name
                prog_dt = row.find('dt', class_='pipe__prog')
                treatment_name = ""
                if prog_dt:
                    link = prog_dt.find('a')
                    if link:
                        treatment_name = link.get_text(strip=True)

                # Phase
                phase = ""
                tracker_dd = row.find('dd', class_='pipe__tracker')
                if tracker_dd:
                    phase_el = tracker_dd.find('strong')
                    if phase_el:
                        phase = phase_el.get_text(strip=True)

                # Partners
                partners = []
                partner_images = []
                partners_dd = row.find('dd', class_='pipe__partners')
                if partners_dd:
                    partner_imgs = partners_dd.find_all('img')
                    for img in partner_imgs:
                        alt_text = img.get('alt', '').strip()
                        src_url = img.get('src', '')
                        if alt_text:
                            partners.append(alt_text)
                        if src_url:
                            partner_images.append(src_url)

                record = {
                    "therapeutic_area": therapeutic_area,
                    "treatment_name": treatment_name,
                    "phase": phase,
                    "partners": partners,
                    "partner_images": partner_images
                }
                pipeline_data.append(record)

        # ----------------------------------------
        # 2) CONVERT TO MasterTable OBJECTS
        # ----------------------------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            # Clean / standardize
            raw_therapeutic_area = clean_text(entry["therapeutic_area"])
            raw_treatment_name   = clean_text(entry["treatment_name"])
            raw_phase            = clean_phase(entry["phase"])   # if you want your custom phase-cleaning
            raw_partners         = entry["partners"]             # these are lists
            raw_partner_images   = entry["partner_images"]       # also lists

            # Build multiline strings for partners & images (or store as you wish)
            partners_str = ", ".join(raw_partners) if raw_partners else ""
            partner_imgs_str = ", ".join(raw_partner_images) if raw_partner_images else ""

            # We'll store each field as its own multilingual collection
            ta_trans = MultilingualData()
            ta_trans.add_translation("en", raw_therapeutic_area)
            ta_collection = MultilingualDataCollection()
            ta_collection.add_data(ta_trans)

            tn_trans = MultilingualData()
            tn_trans.add_translation("en", raw_treatment_name)
            tn_collection = MultilingualDataCollection()
            tn_collection.add_data(tn_trans)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", raw_phase)
            phase_collection = MultilingualDataCollection()
            phase_collection.add_data(phase_trans)

            partners_trans = MultilingualData()
            partners_trans.add_translation("en", partners_str)
            partners_collection = MultilingualDataCollection()
            partners_collection.add_data(partners_trans)

            # identification_key helps avoid duplicates
            identification_key = generate_identification_key(
                "Zealand Pharma",
                raw_therapeutic_area,
                raw_treatment_name,
                raw_phase
            )

            # MasterTable record. 
            # (Below assumes MasterTable can accept these extra fields or you adapt as needed.)
            treatment_key = (raw_therapeutic_area, raw_treatment_name, raw_phase, partners_str, partner_imgs_str)
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Zealand Pharma",
                    therapeutic_area=ta_collection.get_collection_as_json(),
                    treatment_name=tn_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    partner=partners_collection.get_collection_as_json(),
                    partner_images=partner_imgs_str,
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Zealand Pharma.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Zealand's Pipeline: {e}")
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Zealand script: {e}. Please investigate!"
        )
        return []