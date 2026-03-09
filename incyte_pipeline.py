from function_app import (
    fetch_with_zyte,
    clean_phase,
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)
from datetime import datetime, timezone
from bs4 import BeautifulSoup, NavigableString, Tag
import logging
import re

# -----------------------------------------------------
# Fetch HTML Function
# -----------------------------------------------------
async def fetch_incyte_html():
    """
    Returns the Incyte pipeline URL.
    """
    try:
        url = "https://www.incyte.com/what-we-do/pharmaceutical-portfolio"
        return url
    except Exception as e:
        logging.error(f"Error fetching Incyte pipeline URL: {e}")
        return None


# -----------------------------------------------------
# Helper: parse_incyte_footnotes
# -----------------------------------------------------
def parse_incyte_footnotes(soup):
    """
    1) Gather text from ALL div.field--name-bp-text blocks.
    2) Regex out footnotes like '1. Some text' up to '2.' or end-of-string.
    3) Return a dict like {'1': 'Marketed by Incyte...', '2': 'Approved in the U.S.', ...}.
    """
    bp_text_divs = soup.select("div.field--name-bp-text")
    if not bp_text_divs:
        logging.info("No div.field--name-bp-text found at all.")
        return {}

    all_paragraphs_text = []
    for div_el in bp_text_divs:
        paragraphs = div_el.find_all("p")
        for p_tag in paragraphs:
            all_paragraphs_text.append(p_tag.get_text(separator=" ", strip=True))

    combined_text = " ".join(all_paragraphs_text)
    combined_text = re.sub(r"\s+", " ", combined_text).strip()

    logging.info("Combined footnotes text:\n" + combined_text)

    pattern = r"(\d+)\.\s*(.*?)(?=(?:\d+\.\s)|$)"
    matches = re.findall(pattern, combined_text, flags=re.DOTALL)

    footnotes_map = {}
    for num, note_text in matches:
        footnotes_map[num] = note_text.strip()

    logging.info(f"Found {len(footnotes_map)} footnotes.")
    for k, v in footnotes_map.items():
        logging.info(f"Footnote {k} => {v}")

    return footnotes_map


# -----------------------------------------------------
# Helper: parse_indications_with_chunks
# -----------------------------------------------------
def parse_indications_with_chunks(indication_html, footnotes_map):
    """
    Given an HTML string like:
      'Rheumatoid arthritis<sup>12</sup>, COVID-19<sup>12</sup>, AD<sup>5,7</sup>, alopecia areata<sup>12</sup>'
    we produce multiple chunks, e.g.:
      [
        {"text": "Rheumatoid arthritis", "footnotes": [...footnotes for sup=12...]},
        {"text": "COVID-19",            "footnotes": [...footnotes for sup=12...]},
        {"text": "AD",                  "footnotes": [...footnotes for sup=5,7...]},
        {"text": "alopecia areata",     "footnotes": [...footnotes for sup=12...]},
      ]
    We do a mini parser that accumulates text plus <sup> references, splitting at top-level commas.
    """

    # Remove bracket references like [2], [7]
    cleaned_html = re.sub(r"\[\d+\]", "", indication_html)
    soup = BeautifulSoup(cleaned_html, "html.parser")

    chunks = []
    current_text = []
    current_footnotes = []

    def finalize_chunk():
        text_str = "".join(current_text).strip()
        text_str = re.sub(r"\s+", " ", text_str).strip(", ")
        if text_str:
            # remove duplicates (preserve order) in footnotes
            final_notes = list(dict.fromkeys(current_footnotes))
            chunks.append({
                "text": text_str,
                "footnotes": final_notes
            })

    for node in soup.children:
        if isinstance(node, NavigableString):
            # It's text, may contain commas
            text_val = str(node)
            parts = text_val.split(",")
            for i, part in enumerate(parts):
                if i == 0:
                    current_text.append(part)
                else:
                    # a comma => end of chunk
                    finalize_chunk()
                    current_text = [part]
                    current_footnotes = []
        elif isinstance(node, Tag):
            if node.name == "sup":
                # e.g. <sup>5,7</sup>
                sup_content = node.get_text(strip=True)
                for ref_num in sup_content.split(","):
                    ref_num = ref_num.strip()
                    if ref_num.isdigit() and ref_num in footnotes_map:
                        current_footnotes.append(footnotes_map[ref_num])
            else:
                # Some other tag => treat as text
                text_val = node.get_text(" ", strip=True)
                current_text.append(text_val)
        else:
            pass  # comment, doctype, etc.

    # finalize last chunk
    finalize_chunk()
    return chunks


# -----------------------------------------------------
# Process HTML Function
# -----------------------------------------------------
async def process_incyte_html(html_content):
    """
    1) Parse footnotes.
    2) For each product row, remove <sup> from product name display
       but still gather footnotes from product name.
    3) Parse each comma-separated indication chunk with parse_indications_with_chunks,
       localizing footnotes for each chunk.
    4) Build a MasterTable entry per chunk.
    5) Extract the 'Therapeutic Area' text only from .acc-title to avoid "Close/Open".
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Incyte pipeline.")
            # You could decide to send an SMS if you get empty content
            send_sms(
                phone_number="9144334333", 
                message="Incyte script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # 1) "Updated as of..."
        updated_paragraph = soup.select_one("div.field--name-bp-text p.updated-date")
        updated_text = updated_paragraph.get_text(strip=True) if updated_paragraph else ""
        logging.info(f"Last Updated: {updated_text}")

        # 2) Build footnotes map
        footnotes_map = parse_incyte_footnotes(soup)
        logging.info(f"Parsed {len(footnotes_map)} footnotes from pipeline page.")

        treatments = []
        processed_treatments = set()

        # 3) Scrape each "Therapeutic Area" block
        accordion_rows = soup.select("div.view-content .products-rows.views-row.accordion-row")

        for row in accordion_rows:
            header_tag = row.find("h3", class_="js-views-accordion-group-header")
            if not header_tag:
                continue

            # Instead of header_tag.get_text(strip=True), only scrape .acc-title
            acc_title_div = header_tag.select_one(".acc-title")
            if acc_title_div:
                therapeutic_area = acc_title_div.get_text(strip=True)
            else:
                therapeutic_area = ""

            accordion_content = header_tag.find_next("div", class_="ui-accordion-content")
            if not accordion_content:
                continue

            product_divs = accordion_content.select(".row.product.show-prod.porfolio-container")

            for div in product_divs:
                # -------------------------------------------------
                # Product name
                # -------------------------------------------------
                product_name_tag = div.select_one(".product-name p")
                if product_name_tag:
                    product_name_html = product_name_tag.decode_contents()
                else:
                    product_name_html = ""

                # Gather product name <sup> references
                product_name_sups = re.findall(r"<sup>([^<]+)</sup>", product_name_html)
                product_name_footnotes = []
                for sup_val in product_name_sups:
                    for ref_num in sup_val.split(","):
                        ref_num = ref_num.strip()
                        if ref_num.isdigit() and ref_num in footnotes_map:
                            product_name_footnotes.append(footnotes_map[ref_num])

                # Remove <sup> from the displayed product name
                product_name_display = re.sub(r"<sup>[^<]+</sup>", "", product_name_html)
                product_name_display = BeautifulSoup(product_name_display, "html.parser").get_text(strip=True)
                product_name_display = re.sub(r"\[\d+\]", "", product_name_display).strip()

                # -------------------------------------------------
                # Molecule
                # -------------------------------------------------
                molecule_tag = div.select_one(".product-molecule")
                molecule = molecule_tag.get_text(strip=True) if molecule_tag else ""

                # -------------------------------------------------
                # Phase
                # -------------------------------------------------
                phase = "unknown"  # default
                phase_div = div.select_one(".status-line.product-phase")
                if phase_div and phase_div.has_attr("class"):
                    classes = phase_div["class"]
                    found_phase = None
                    for possible_phase in ["approved", "pivotal", "clinical-proof-of-concept"]:
                        if possible_phase in classes:
                            found_phase = possible_phase
                            break

                    # If none of the expected ones matched:
                    if found_phase:
                        phase = clean_phase(found_phase)
                    else:
                        # maybe there's a fallback text you can read from the HTML
                        text_fallback = phase_div.get_text(strip=True)
                        phase = clean_phase(text_fallback) if text_fallback else "unknown"


                # -------------------------------------------------
                # Indication HTML => parse chunk by chunk
                # -------------------------------------------------
                indication_tag = div.select_one(".product-state p")
                indication_html = indication_tag.decode_contents() if indication_tag else ""

                # parse chunk-level
                chunks = parse_indications_with_chunks(indication_html, footnotes_map)
                # => e.g. [ {"text":"Rheumatoid arthritis", "footnotes":[...12...]}, {"text":"AD", "footnotes":[...5,7...]} ]

                # Combine product name footnotes with chunk footnotes if you want them in each chunk
                for c in chunks:
                    all_notes = product_name_footnotes + c["footnotes"]
                    dedup_notes = list(dict.fromkeys(all_notes))

                    indication_display = c["text"]
                    notes_text = "; ".join(dedup_notes) if dedup_notes else ""

                    # Build identification key
                    identification_key = generate_identification_key(
                        "Incyte",
                        product_name_display,
                        therapeutic_area,
                        indication_display
                    )

                    record_key = (
                        therapeutic_area,
                        product_name_display,
                        molecule,
                        indication_display,
                        phase
                    )

                    if record_key not in processed_treatments:
                        date_scraped = datetime.now(timezone.utc)

                        # Build multilingual fields if needed
                        area_trans = MultilingualData()
                        area_trans.add_translation("en", therapeutic_area)

                        product_trans = MultilingualData()
                        product_trans.add_translation("en", product_name_display)

                        molecule_trans = MultilingualData()
                        molecule_trans.add_translation("en", molecule)

                        indication_trans = MultilingualData()
                        indication_trans.add_translation("en", indication_display)

                        phase_trans = MultilingualData()
                        phase_trans.add_translation("en", phase)

                        notes_trans = MultilingualData()
                        notes_trans.add_translation("en", notes_text)

                        name_trans = MultilingualData()
                        name_trans.add_translation("en", product_name_display)

                        date_updated_trans = MultilingualData()
                        date_updated_trans.add_translation("en", updated_text)

                        area_collection = MultilingualDataCollection()
                        product_collection = MultilingualDataCollection()
                        molecule_collection = MultilingualDataCollection()
                        indication_collection = MultilingualDataCollection()
                        phase_collection = MultilingualDataCollection()
                        notes_collection = MultilingualDataCollection()
                        name_collection = MultilingualDataCollection()
                        date_update_collection = MultilingualDataCollection()

                        area_collection.add_data(area_trans)
                        product_collection.add_data(product_trans)
                        molecule_collection.add_data(molecule_trans)
                        indication_collection.add_data(indication_trans)
                        phase_collection.add_data(phase_trans)
                        notes_collection.add_data(notes_trans)
                        name_collection.add_data(name_trans)
                        date_update_collection.add_data(date_updated_trans)

                        master_record = MasterTable(
                            company_name="Incyte",
                            treatment_name=name_collection.get_collection_as_json(),
                            indication=indication_collection.get_collection_as_json(),
                            therapeutic_area=area_collection.get_collection_as_json(),
                            phase=phase_collection.get_collection_as_json(),
                            target=molecule_collection.get_collection_as_json(),
                            date_scraped=date_scraped,
                            identification_key=identification_key,
                            date_last_changed=date_update_collection.get_collection_as_json(),
                            notes=notes_collection.get_collection_as_json(),
                        )

                        treatments.append(master_record.__dict__)
                        processed_treatments.add(record_key)

        logging.info(f"Processed {len(treatments)} treatments for Incyte.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Incyte's Pipeline: {e}")
        # 1) We can also send an SMS containing the error message
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Incyte script: {e}. Please investigate!"
        )
        # 2) Return an empty list or re-raise the exception
        return []