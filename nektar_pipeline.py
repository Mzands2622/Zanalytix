# nektar_pipeline.py

import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# Adjust these imports to match your project structure:
from function_app import (
    fetch_with_zyte,
    clean_text,
    clean_phase,  # Or keep your own logic for the phases if desired
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)


async def fetch_nektar_html():
    """
    Fetches the Nektar pipeline page via Zyte.
    """
    try:
        url = "https://www.nektar.com/pipeline/rd-pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching Nektar HTML: {e}")
        return None


def parse_nektar_pipeline_html(html_content):
    """
    Low-level parsing of Nektar pipeline data from the raw HTML.
    Returns a list of dictionaries with keys:
      therapeutic_area, disease_area, indication, treatment_name, target,
      phase, partners, nct_numbers, notes
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")

    # ========================================================================
    # 1) Identify the pipeline div and collect footnotes AFTER it.
    # ========================================================================
    pipeline_div = soup.select_one("div.pipeline.block_ce4caae2d301546229ada1c631c1f13f")
    footnotes = {}
    if pipeline_div:
        parent_col = pipeline_div.find_parent("div", class_="col-12")
        if parent_col:
            # Collect siblings AFTER pipeline_div in this parent
            siblings_after = []
            found_pipeline_div = False
            for child in parent_col.children:
                if child is pipeline_div:
                    found_pipeline_div = True
                    continue
                if found_pipeline_div and hasattr(child, "name") and child.name:
                    siblings_after.append(child)

            # Among these siblings, gather any <p> tags as footnotes
            footnote_paragraphs = []
            for sibling in siblings_after:
                if sibling.name == "p":
                    footnote_paragraphs.append(sibling)
                else:
                    footnote_paragraphs.extend(sibling.select("p"))

            # Build footnote map from these paragraphs
            for p_tag in footnote_paragraphs:
                text = p_tag.get_text(strip=True)
                if text:
                    first_char = text[0]
                    note_text = text[1:].lstrip()
                    footnotes[first_char] = note_text

    # ========================================================================
    # 2) Parse the pipeline items
    # ========================================================================
    results = []
    pipeline_rows = soup.select("div.pipeline-item__row")
    for row in pipeline_rows:
        therapeutic_area = row.get("data-therapeutic-area", "").strip()

        # Disease area & indication
        disease_area = ""
        indication = ""
        cd_div = row.select_one("div.pipeline-item__condition-disease")
        if cd_div:
            disease_area_el = cd_div.select_one("h4")
            if disease_area_el:
                disease_area = disease_area_el.get_text(strip=True)
            condition_el = cd_div.select_one("p")
            if condition_el:
                indication = condition_el.get_text(strip=True)

        # Treatment name
        treatment_name = ""
        agents_div = row.select_one("div.pipeline-item__agents")
        if agents_div:
            treatment_name = agents_div.get_text(" ", strip=True)

        # Target (Mechanism)
        target = ""
        mechanism_links = []
        mechanism_div = row.select_one("div.pipeline-item__mechanism")
        if mechanism_div:
            target = mechanism_div.get_text(" ", strip=True)
            for link_tag in mechanism_div.select("a"):
                href = link_tag.get("href", "").strip()
                if href:
                    mechanism_links.append(href)

        # Phase
        phase = ""
        phase_div = row.select_one("div.pipeline-item__phase-name")
        if phase_div:
            phase = phase_div.get_text(strip=True)

        # Partners (list)
        partners = []
        partner_div = row.select_one("div.pipeline-item__partner")
        if partner_div:
            partner_imgs = partner_div.select("img")
            if partner_imgs:
                for p_img in partner_imgs:
                    src = p_img.get("src", "").strip()
                    if src:
                        partners.append(src)
            else:
                partner_text = partner_div.get_text(strip=True)
                if partner_text:
                    partners.append(partner_text)

        # NCT numbers
        nct_numbers = []
        for nct_anchor in row.select("div.nct-number a"):
            raw_text = nct_anchor.get_text(strip=True)
            if raw_text:
                nct_numbers.append(raw_text)

        # Build initial dictionary
        row_data = {
            "therapeutic_area": therapeutic_area,
            "disease_area": disease_area,
            "indication": indication,
            "treatment_name": treatment_name,
            "target": target,
            "phase": phase,
            "partners": partners,
            "nct_numbers": nct_numbers,
            # Start notes with the mechanism links (we can add footnotes next)
            "notes": mechanism_links[:],
        }

        # ====================================================================
        # 3) Check for footnote keys in the pipeline item text
        # ====================================================================
        relevant_text_parts = [
            therapeutic_area, disease_area, indication, treatment_name, target, phase
        ]
        relevant_text_parts.extend(partners)
        relevant_text_parts.extend(nct_numbers)
        combined_text = " ".join(relevant_text_parts)

        for fn_key, fn_text in footnotes.items():
            if fn_key in combined_text:
                if fn_text not in row_data["notes"]:
                    row_data["notes"].append(fn_text)

        results.append(row_data)

    return results


async def process_nektar_html(html_content):
    """
    Parses Nektar pipeline HTML, logs errors, cleans fields, and returns
    a list of MasterTable objects (in dict form).
    
    Identification key = (treatment_name, indication, disease_area, therapeutic_area).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Nektar pipeline.")
            send_sms(
                phone_number="9144334333",
                message="Nektar script returned no HTML content. Please investigate!"
            )
            return []

        raw_data = parse_nektar_pipeline_html(html_content)
        if not raw_data:
            logging.warning("No pipeline entries found in Nektar HTML.")
            send_sms(
                phone_number="9144334333",
                message="Nektar script found no pipeline data. Please investigate!"
            )
            return []

        results = []
        processed_entries = set()

        for item in raw_data:
            raw_therapeutic_area = item.get("therapeutic_area", "")
            raw_disease_area = item.get("disease_area", "")
            raw_indication = item.get("indication", "")
            raw_treatment_name = item.get("treatment_name", "")
            raw_target = item.get("target", "")
            raw_phase = item.get("phase", "")
            raw_partners = item.get("partners", [])
            raw_nct_numbers = item.get("nct_numbers", [])
            raw_notes_list = item.get("notes", [])

            # Convert partners & nct_numbers to comma-joined if needed
            combined_partners = ", ".join(raw_partners) if raw_partners else ""
            combined_nct = ", ".join(raw_nct_numbers) if raw_nct_numbers else ""
            combined_notes = "\n".join(raw_notes_list) if raw_notes_list else ""

            # Clean text
            therapeutic_area = clean_text(raw_therapeutic_area)
            disease_area = clean_text(raw_disease_area)
            indication = clean_text(raw_indication)
            treatment_name = clean_text(raw_treatment_name)
            target = clean_text(raw_target)
            # Optionally unify phases with clean_phase
            # phase = clean_phase(raw_phase)
            phase = clean_phase(raw_phase)
            partners = clean_text(combined_partners)
            nct_numbers = clean_text(combined_nct)
            notes = clean_text(combined_notes)

            # Build identification key
            identification_key = generate_identification_key(
                "Nektar",
                treatment_name,
                indication,
                disease_area,
            )

            # Wrap data in multilingual structures
            ta_trans = MultilingualData()
            disease_trans = MultilingualData()
            indication_trans = MultilingualData()
            treatment_trans = MultilingualData()
            target_trans = MultilingualData()
            phase_trans = MultilingualData()
            partner_trans = MultilingualData()
            nct_trans = MultilingualData()
            notes_trans = MultilingualData()

            ta_trans.add_translation("en", therapeutic_area)
            disease_trans.add_translation("en", disease_area)
            indication_trans.add_translation("en", indication)
            treatment_trans.add_translation("en", treatment_name)
            target_trans.add_translation("en", target)
            phase_trans.add_translation("en", phase)
            partner_trans.add_translation("en", partners)
            nct_trans.add_translation("en", nct_numbers)
            notes_trans.add_translation("en", notes)

            ta_coll = MultilingualDataCollection()
            disease_coll = MultilingualDataCollection()
            indication_coll = MultilingualDataCollection()
            treatment_coll = MultilingualDataCollection()
            target_coll = MultilingualDataCollection()
            phase_coll = MultilingualDataCollection()
            partner_coll = MultilingualDataCollection()
            nct_coll = MultilingualDataCollection()
            notes_coll = MultilingualDataCollection()

            ta_coll.add_data(ta_trans)
            disease_coll.add_data(disease_trans)
            indication_coll.add_data(indication_trans)
            treatment_coll.add_data(treatment_trans)
            target_coll.add_data(target_trans)
            phase_coll.add_data(phase_trans)
            partner_coll.add_data(partner_trans)
            nct_coll.add_data(nct_trans)
            notes_coll.add_data(notes_trans)

            # Unique record key to avoid duplicates
            record_key = (
                therapeutic_area, disease_area, indication, treatment_name, phase, notes
            )
            if record_key not in processed_entries:
                master_record = MasterTable(
                    company_name="Nektar",
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,

                    therapeutic_area=ta_coll.get_collection_as_json(),
                    disease_area=disease_coll.get_collection_as_json(),
                    indication=indication_coll.get_collection_as_json(),
                    treatment_name=treatment_coll.get_collection_as_json(),
                    target=target_coll.get_collection_as_json(),
                    phase=phase_coll.get_collection_as_json(),
                    partner=partner_coll.get_collection_as_json(),
                    study=nct_coll.get_collection_as_json(),
                    notes=notes_coll.get_collection_as_json()
                )

                results.append(master_record.__dict__)
                processed_entries.add(record_key)

        logging.info(f"Processed {len(results)} pipeline entries for Nektar.")
        return results

    except Exception as e:
        logging.error(f"An error occurred scraping Nektar's pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in Nektar's script: {e}. Please investigate!"
        )
        return []