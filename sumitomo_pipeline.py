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
import re  # <-- ADDED for handling parentheses


# -----------------------
# Fetch HTML Function
# -----------------------
async def fetch_sumitomo_html():
    """
    Fetches the Sumitomo pipeline HTML content by calling fetch_with_zyte.
    Returns:
        (str | None): The raw HTML content of the Sumitomo pipeline page, or
                      None if an error occurred.
    """
    try:
        url = "https://www.sumitomo-pharma.com/rd/pipeline_new-medicine/pipeline.html"
        return url
    except Exception as e:
        logging.error(f"Error fetching Sumitomo pipeline HTML: {e}", exc_info=True)
        return None


def parse_table_with_rowspan(table, total_cols):
    """
    Reads the given <table> and returns a list of 'logical rows,' each row
    represented as a list of strings of length `total_cols`, respecting
    any 'rowspan' attributes (i.e., duplicates cell values to subsequent rows).

    Args:
        table (BeautifulSoup element): The <table> to parse.
        total_cols (int): Number of columns in the table.

    Returns:
        list[list[str]]: A list of 'logical' rows, each exactly `total_cols` wide.
    """
    master_matrix = []
    # Track (text, rows_left) for each column so we can fill them downward
    pending_rowspan = [None] * total_cols

    # Grab all table rows in the <tbody> (and <thead> if data is in <th>)
    all_rows = table.find_all('tr')

    for tr in all_rows:
        # If the row is purely a header row and you want to skip it entirely:
        ths = tr.find_all('th', recursive=False)
        # If you want to treat <th> as data, you could handle them instead of skipping.
        if len(ths) == total_cols:
            # Typically you'd skip a pure header row, but comment out if you want them:
            continue

        # Build an array of length total_cols for this row
        row_cells = [None] * total_cols

        # First, fill in any rowspans from above
        for col_idx, p in enumerate(pending_rowspan):
            if p is not None:
                text_value, rows_left = p
                row_cells[col_idx] = text_value
                if rows_left > 1:
                    pending_rowspan[col_idx] = (text_value, rows_left - 1)
                else:
                    pending_rowspan[col_idx] = None

        # Now read <td> in this row
        col_i = 0
        cells = tr.find_all('td', recursive=False)
        for cell in cells:
            # Move forward to the next empty slot in row_cells
            while col_i < total_cols and row_cells[col_i] is not None:
                col_i += 1
            if col_i >= total_cols:
                break

            text_value = cell.get_text(strip=True)

            # Place the text in the correct slot
            row_cells[col_i] = text_value

            # Handle rowspan
            rs = cell.get('rowspan')
            if rs and rs.isdigit():
                span_count = int(rs)
                if span_count > 1:
                    # We'll fill down for (span_count - 1) subsequent rows
                    pending_rowspan[col_i] = (text_value, span_count - 1)

            col_i += 1

        master_matrix.append(row_cells)

    return master_matrix


def get_table_column_count(table):
    """
    Attempt to determine how many columns a <table> has by looking at:
    1) <colgroup> if present, or
    2) the maximum number of <th>/<td> found in any single row in the table.

    Returns:
        int: number of columns
    """
    colgroup = table.find('colgroup')
    if colgroup:
        cols = colgroup.find_all('col')
        if cols:
            return len(cols)

    # Fallback: find the max number of <td> or <th> in any row
    max_cols = 0
    for tr in table.find_all('tr'):
        cell_count = len(tr.find_all(['td', 'th'], recursive=False))
        if cell_count > max_cols:
            max_cols = cell_count
    return max_cols


# -----------------------
# Process HTML Function
# -----------------------
async def process_sumitomo_html(html_content):
    """
    Processes the Sumitomo pipeline HTML content and extracts treatment information.

    Args:
        html_content (str): Raw HTML content for the Sumitomo pipeline page.

    Returns:
        list: A list of extracted treatment records, each represented as
              a dictionary (or optionally a serialized MasterTable object).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Sumitomo pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Sumitomo script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        treatments = []
        dsp_count = 0

        # 1) Find each <h2> section that marks a therapeutic area.
        sections = soup.find_all('h2', class_='c-hdg-level2-01')
        for section in sections:
            therapeutic_area = section.get_text(strip=True)

            # 2) For each section, find the first <table> that follows it
            table = section.find_next('table', class_='c-tbl-data-01')
            if not table:
                continue

            # 3) Automatically detect how many columns are in the table
            total_cols = get_table_column_count(table)

            # 4) Parse the table with our row-span–aware parser
            matrix = parse_table_with_rowspan(table, total_cols)

            # 5) Interpret the columns.  
            #    For the 5-col table (Psychiatry & Neurology), columns are:
            #      [0]=subcategory, [1]=name, [2]=indication, [3]=region, [4]=stage
            #    For the 4-col table (Oncology, Others), columns are:
            #      [0]=name, [1]=indication, [2]=region, [3]=stage
            subcategory = ""

            for row in matrix:
                # If this row is all None/empty, skip
                if not any(cell for cell in row):
                    continue

                if total_cols == 5:
                    col0, col1, col2, col3, col4 = row
                    # If there's text only in col0, and the rest are blank,
                    # it’s a subcategory row (e.g. "Small molecule")
                    if col0 and not any([col1, col2, col3, col4]):
                        subcategory = col0
                        continue

                    # Otherwise interpret them
                    treatment_name = col1 or ""
                    indication = col2 or ""
                    region = col3 or ""
                    development_stage = col4 or ""

                else:
                    # 4 columns
                    col0, col1, col2, col3 = row
                    treatment_name = col0 or ""
                    indication = col1 or ""
                    region = col2 or ""
                    development_stage = col3 or ""

                # Skip if there's no stage
                if not development_stage:
                    continue

                # Example logic: skip DSP-2342 the second time
                if treatment_name == "DSP-2342":
                    if dsp_count == 1:
                        continue
                    dsp_count += 1

                # If we see "CT1-DAP001" or "HLCR011," we can override subcategory
                if "CT1-DAP001" in treatment_name or "HLCR011" in treatment_name:
                    subcategory = "Regenerative medicine / cell therapy"

                # --------------------------------------------------
                # Extract parentheses from the development_stage
                # --------------------------------------------------
                # e.g., "Phase 1/2 (Investigator-initiated study)"
                # we'll move the parentheses text into `study_text`.
                study_text = None
                pattern = r"\(([^)]+)\)"
                match = re.search(pattern, development_stage)
                if match:
                    # Extract the parentheses content (without parentheses)
                    study_text = match.group(1).strip()
                    # Remove the parentheses part from `development_stage`
                    development_stage = re.sub(pattern, "", development_stage).strip()

                treatments.append({
                    "Therapeutic Area": therapeutic_area,
                    "Subcategory": subcategory,
                    "Treatment Name": treatment_name,
                    "Indication": indication,
                    "Region": region,
                    "Development Stage": development_stage,
                    "Study": study_text  # temporary hold in dictionary
                })

        # Now build your MasterTable records
        master_records = []
        date_scraped = datetime.now(timezone.utc)

        for item in treatments:
            therapeutic_area = clean_text(item.get("Therapeutic Area", ""))
            subcategory = clean_text(item.get("Subcategory", ""))
            treatment_name = clean_text(item.get("Treatment Name", ""))
            indication = clean_text(item.get("Indication", ""))
            region = clean_text(item.get("Region", ""))
            development_stage = clean_phase(item.get("Development Stage", ""))
            study_text = clean_text(item.get("Study", ""))  # new study text

            # Create an identification key (example usage)
            identification_key = generate_identification_key(
                "Sumitomo",
                treatment_name,
                indication,
                region,
                study_text
            )

            # Build multilingual data
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            subcat_trans = MultilingualData()
            subcat_trans.add_translation("en", subcategory)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            region_trans = MultilingualData()
            region_trans.add_translation("en", region)

            dev_stage_trans = MultilingualData()
            dev_stage_trans.add_translation("en", development_stage)

            # Build a new multilingual collection for study text
            study_trans = MultilingualData()
            study_trans.add_translation("en", study_text)

            name_trans = MultilingualData()
            name_trans.add_translation("en", treatment_name)

            # Create data collections
            area_collection = MultilingualDataCollection()
            subcat_collection = MultilingualDataCollection()
            indication_collection = MultilingualDataCollection()
            region_collection = MultilingualDataCollection()
            dev_stage_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()  # new
            name_collection = MultilingualDataCollection()

            area_collection.add_data(area_trans)
            subcat_collection.add_data(subcat_trans)
            indication_collection.add_data(indication_trans)
            region_collection.add_data(region_trans)
            dev_stage_collection.add_data(dev_stage_trans)
            study_collection.add_data(study_trans)  # new
            name_collection.add_data(name_trans)

            # Create MasterTable object
            # Make sure the MasterTable class can accept 'study' (or set it after creation).
            master_record = MasterTable(
                company_name="Sumitomo Pharma",
                treatment_name=name_collection.get_collection_as_json(),
                indication=indication_collection.get_collection_as_json(),
                therapeutic_area=area_collection.get_collection_as_json(),
                phase=dev_stage_collection.get_collection_as_json(),
                type_of_molecule=subcat_collection.get_collection_as_json(),
                country=region_collection.get_collection_as_json(),
                date_scraped=date_scraped,
                identification_key=identification_key,
                # If your MasterTable supports a 'study' field:
                study=study_collection.get_collection_as_json()
            )

            master_records.append(master_record.__dict__)

        logging.info(f"Processed {len(master_records)} treatments for Sumitomo.")
        return master_records

    except Exception as e:
        logging.error(f"An error occurred scraping Sumitomo Pharma's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Sumitomo Pharma script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []