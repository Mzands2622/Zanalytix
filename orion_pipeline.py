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

async def fetch_orion_html():
    try:
        # Fetch HTML using Zyte API
        url = "https://www.orion.fi/en/science/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Otsuka HTML: {e}")
        return None

def parse_orion_item(li_item):
    """
    Given one <li class="accordion-list__item">,
    parse and return a dict with pipeline info:
      - drug_name
      - indication
      - phase
      - study
      - partner
      - more_info
    """

    # -- 1) Extract heading text, e.g.:
    # "Opevesostat » prostate cancer (mCRPC) » Phase III OMAHA2a"
    heading_span = li_item.select_one('h3 .mr-15')
    heading_text = heading_span.get_text(strip=True) if heading_span else ""

    # We'll split by '»' to get [drug_name, short_indication, pipeline_stage]
    parts = [p.strip() for p in heading_text.split('»')]
    if len(parts) == 3:
        drug_name = parts[0]
        short_indication = parts[1]
        pipeline_stage = parts[2]
    elif len(parts) == 2:
        drug_name = parts[0]
        short_indication = parts[1]
        pipeline_stage = ""
    else:
        # Fallback if something doesn't match
        drug_name = heading_text
        short_indication = ""
        pipeline_stage = ""

    # -- 2) Split pipeline_stage into "phase" and "study".
    # Examples:
    #   "Registration"         -> phase="Registration", study=""
    #   "Phase IIa"           -> phase="Phase IIa",     study=""
    #   "Phase III OMAHA2a"   -> phase="Phase III",     study="OMAHA2a"
    #   "Phase IIa OMAHA2"    -> phase="Phase IIa",     study="OMAHA2"
    # We'll handle these by splitting on whitespace, then re-group.
    splitted = pipeline_stage.split()

    if len(splitted) == 0:
        # pipeline_stage was empty
        phase = ""
        study = ""
    elif len(splitted) == 1:
        # e.g. "Registration"
        phase = splitted[0]
        study = ""
    else:
        # We have at least two segments
        # if the first segment is "Phase" (case-insensitive),
        # and the second segment is something like "IIa", "III", etc...
        # we'll combine them: "Phase IIa".
        # Then everything else becomes the study.
        first = splitted[0].capitalize()  # "Phase"
        second = splitted[1]

        if first.lower() == "phase":
            # Combine e.g. "Phase" + "IIa"
            phase = f"{first} {second}"
            # If there's more than 2 segments, join them for study
            if len(splitted) > 2:
                study = " ".join(splitted[2:])
            else:
                study = ""
        else:
            # If the first segment isn't "Phase", we can just do:
            # phase = splitted[0], study = splitted[1...]
            # But let's unify the logic so that e.g. "Late Stage"
            # or "Registration OMAHA2" is also handled.
            phase = splitted[0]
            if len(splitted) > 1:
                study = " ".join(splitted[1:])
            else:
                study = ""

    # -- 3) Now parse the detail <div> for "Indication:", "Partner:", "Status:", etc.
    detail_div = li_item.select_one('div[data-toggle-target]')
    indication = ""
    partner = ""
    more_info = ""

    if detail_div:
        paragraphs = detail_div.select('p')
        label = None
        for p in paragraphs:
            strong_tag = p.select_one('strong')
            if strong_tag:
                label_text = strong_tag.get_text(strip=True).lower()
                leftover = p.get_text(strip=True).replace(strong_tag.get_text(strip=True), "").strip(": ")

                if label_text.startswith("indication"):
                    if leftover:
                        indication = leftover
                    else:
                        label = "indication"

                elif label_text.startswith("partner"):
                    if leftover:
                        partner = leftover
                    else:
                        label = "partner"

                elif label_text.startswith("status"):
                    if leftover:
                        more_info = leftover
                    else:
                        label = "status"

            else:
                # If no <strong>, maybe it's the next line of a label
                if label == "indication":
                    indication = p.get_text(strip=True)
                    label = None
                elif label == "partner":
                    partner = p.get_text(strip=True)
                    label = None
                elif label == "status":
                    more_info = p.get_text(strip=True)
                    label = None

    return {
        "drug_name": drug_name,
        "indication": indication,
        "phase": phase,
        "study": study,
        "partner": partner,
        "more_info": more_info
    }



# -----------------------
# Process HTML Function
# -----------------------
async def process_orion_html(html_content):
    """
    Parses Orion's pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Orion Corporation pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Orion Corporation script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        accordion_items = soup.select('li.accordion-list__item')
        pipeline_data = []

        for li_item in accordion_items:
            parsed_data = parse_orion_item(li_item)
            pipeline_data.append(parsed_data)

        # ---------------------
        # Convert to MasterTable Objects
        # ---------------------
        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in pipeline_data:
            drug_name = clean_text(entry["drug_name"])
            indication = clean_text(entry["indication"])
            phase = clean_phase(entry["phase"])
            study = clean_text(entry["study"])
            partner = clean_text(entry["partner"])
            more_info = clean_text(entry["more_info"])

            identification_key = generate_identification_key("Orion", drug_name, study, indication)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            study_trans = MultilingualData()
            study_trans.add_translation("en", study)

            partner_trans = MultilingualData()
            partner_trans.add_translation("en", partner)

            info_trans = MultilingualData()
            info_trans.add_translation("en", more_info)

            name_trans = MultilingualData()
            name_trans.add_translation("en", drug_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            # Collections
            indication_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()
            partner_collection = MultilingualDataCollection()
            info_collection = MultilingualDataCollection()
            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()

            indication_collection.add_data(indication_trans)
            study_collection.add_data(study_trans)
            partner_collection.add_data(partner_trans)
            info_collection.add_data(info_trans)
            name_collection.add_data(name_trans)
            phase_collection.add_data(phase_trans)

            treatment_key = (drug_name, indication, phase, study, partner, more_info)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Orion Corporation",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    study=study_collection.get_collection_as_json(),
                    partner=partner_collection.get_collection_as_json(),
                    notes=info_collection.get_collection_as_json(),
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )
                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Orion.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Orion Corporation's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Orion Corporation script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []

