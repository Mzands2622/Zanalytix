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
async def fetch_pharvaris_html():
    """
    Returns the Pharvaris pipeline URL.
    """
    try:
        url = "https://pharvaris.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Pharvaris pipeline URL: {e}")
        return None


# --------------------------------------
# Helper: Convert numeric width to stage
# --------------------------------------
def map_width_to_stage(width_value: float) -> str:
    """
    Convert a numeric width (0-100) to a textual pipeline stage.
    Adjust thresholds if needed.
    """
    if width_value <= 20:
        return "Preclinical"
    elif width_value <= 40:
        return "Phase 1"
    elif width_value <= 60:
        return "Phase 2"
    elif width_value <= 80:
        return "Phase 3"
    else:
        return "Registration"


# --------------------------------------
# Helper: Extract bar and images from a sub-block
# --------------------------------------
def extract_bar_and_images(container_div):
    """
    Given a container (e.g. <div id="sourceDiv"> ...),
    find exactly one bar-with-triangle(ish) div for the numeric width,
    and then gather all <img> tags in that same container.

    Returns a dict like:
      {"width": float or None, "images": [list of strings from alt or src]}
    """
    # Find the bar
    bar_div = container_div.select_one(
        '.bar-with-triangle, .bar-with-triangle-green, .bar-with-triangle-gray, .bar-with-triangle-purple'
    )
    width_val = None
    if bar_div:
        style_attr = bar_div.get('style', '')
        match = re.search(r'width:\s*([\d.]+)%', style_attr)
        if match:
            try:
                width_val = float(match.group(1))
            except ValueError:
                pass

    # Gather all <img> tags
    images = []
    img_tags = container_div.select('img')
    for img in img_tags:
        alt_text = (img.get('alt') or '').strip()
        if alt_text:
            images.append(alt_text)
        else:
            # fallback: store the src if alt is empty
            images.append(img.get('src'))

    return {
        "width": width_val,
        "images": images
    }


# --------------------------------------
# Helper: Parse one .row in the pipeline
# --------------------------------------
def parse_pipeline_row(row_div):
    """
    Parse one <div class="row"> that contains:
      - Column 1: Molecule
      - Column 2: One or more Indications
      - Column 3 (or more): Sub-block containers (#sourceDiv, #sourceDivTwo, etc.)
                            Each container has one bar + multiple <img> tags.

    Returns a list of dicts of the form:
       {
         "molecule": ...,
         "indication": ...,
         "stage": ...,
         "studies": ...
       }
    """
    pipeline_cols = row_div.select('.my-pipeline-col')
    if len(pipeline_cols) < 3:
        return []

    # -- COLUMN 1 (molecule)
    col1_span = pipeline_cols[0].select_one('span')
    molecule = col1_span.get_text(strip=True) if col1_span else ""

    # -- COLUMN 2 (indications)
    col2_divs = pipeline_cols[1].select('div')
    indications = []
    for d in col2_divs:
        sp = d.select_one('span')
        if sp:
            text_clean = sp.get_text(" ", strip=True)
            indications.append(text_clean)

    # -- COLUMN 3 (the big container) might have multiple sub-blocks
    #    Instead of relying on ID strings, let's grab any div that has
    #    a recognizable bar or images:
    sub_block_divs = pipeline_cols[2].select(
        'div#sourceDiv, div#sourceDivTwo, div#sourceDivThree'
    )
    # or if you suspect more, you could do:
    # sub_block_divs = [
    #   d for d in pipeline_cols[2].select('div')
    #   if d.select_one('.bar-with-triangle, .bar-with-triangle-green, .bar-with-triangle-gray, .bar-with-triangle-purple')
    # ]

    bar_info_list = []
    for container in sub_block_divs:
        bar_and_imgs = extract_bar_and_images(container)
        width_val = bar_and_imgs['width']
        stage = map_width_to_stage(width_val) if width_val is not None else None

        bar_info_list.append({
            "stage": stage,
            "studies": bar_and_imgs["images"]
        })

    # Now pair them by index with the indications:
    max_sub = max(len(indications), len(bar_info_list))
    results = []
    for i in range(max_sub):
        indic = indications[i] if i < len(indications) else ""
        bar_data = bar_info_list[i] if i < len(bar_info_list) else {}
        stage = bar_data.get("stage") or ""
        studies = bar_data.get("studies") or []

        results.append({
            "molecule": molecule,
            "indication": indic,
            "stage": stage,
            "studies": studies
        })

    return results


# --------------------------------------
# Async function that returns the pipeline URL
# --------------------------------------
async def fetch_pharvaris_html():
    """
    Returns the Pharvaris pipeline URL.
    (You could fetch or read from DB if there's some logic, 
    but currently just returning the static URL.)
    """
    try:
        url = "https://pharvaris.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Pharvaris pipeline URL: {e}")
        return None


# --------------------------------------
# Main processing function
# --------------------------------------
async def process_pharvaris_html(html_content):
    """
    Parses Pharvaris' pipeline HTML (using our new bar+images logic)
    and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Pharvaris pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Pharvaris script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        pipeline_section = soup.select_one('section.new-pipeline')
        if not pipeline_section:
            logging.error("No <section class=\"new-pipeline\"> found.")
            return []

        pipeline_wrap = pipeline_section.select_one('.new-pipeline-wrap')
        if not pipeline_wrap:
            logging.error("No .new-pipeline-wrap found.")
            return []

        # Each row <div class="row"> might correspond to a separate pipeline item
        rows = pipeline_wrap.select('.row')
        all_parsed_data = []

        for row in rows:
            # Skip the header row
            if 'my-pipeline-header' in row.get('class', []):
                continue

            pipeline_cols = row.select('.my-pipeline-col')
            if not pipeline_cols:
                continue

            row_entries = parse_pipeline_row(row)
            all_parsed_data.extend(row_entries)

        # ---------------------------------------------------------
        # Convert the raw parsed data to MasterTable-like objects
        # ---------------------------------------------------------
        # The new parser returns dicts like:
        #   {
        #     "molecule": "...",
        #     "indication": "...",
        #     "stage": "...",
        #     "studies": [...]
        #   }
        #
        # We want to rename keys for final usage:
        #   "molecule" -> "treatment_name"
        #   "stage" -> "phase"
        #   "studies" -> "study"  (plain list, no multilingual)

        treatments = []
        processed_treatments = set()
        date_scraped = datetime.now(timezone.utc)

        for entry in all_parsed_data:
            treatment_name = clean_text(entry.get("molecule", ""))
            indication = clean_text(entry.get("indication", ""))
            phase = clean_phase(entry.get("stage", ""))
            study_list = entry.get("studies", [])  # This is a plain list of strings (image ALTs or SRCs)

            # If you want to store them as strings, you could do: study_str = ", ".join(study_list)
            # But let's keep them as a raw list in the dictionary.
            # No multilingual needed.

            # Identification key
            identification_key = generate_identification_key(
                "Pharvaris", treatment_name, indication  # no separate "formulation" here
            )

            # MultilingualData for fields we do want
            # - We do want name, indication, phase as multilingual
            # - We do NOT do multilingual for "study" (the images)

            name_trans = MultilingualData()
            name_trans.add_translation("en", treatment_name)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            name_collection = MultilingualDataCollection()
            name_collection.add_data(name_trans)

            indication_collection = MultilingualDataCollection()
            indication_collection.add_data(indication_trans)

            phase_collection = MultilingualDataCollection()
            phase_collection.add_data(phase_trans)

            # Use a tuple of the key fields to avoid duplicates
            treatment_key = (treatment_name, indication, phase)

            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Pharvaris",
                    treatment_name=name_collection.get_collection_as_json(),
                    indication=indication_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    study=study_list,
                    date_scraped=date_scraped,
                    identification_key=identification_key
                )

                # Convert the MasterTable to a dictionary:
                record_dict = master_record.__dict__


                treatments.append(record_dict)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Pharvaris.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Pharvaris's Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Pharvaris script: {e}. Please investigate!"
        )
        return []
