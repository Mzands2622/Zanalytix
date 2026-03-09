import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# We import the same helpers you have in function_app:
from function_app import (
    fetch_with_zyte,      # We'll use this to fetch the HTML content
    clean_text,           # We'll apply this to all textual fields
    clean_phase,          # We'll apply this specifically for the phase
    MasterTable,
    MultilingualData,
    MultilingualDataCollection,
    generate_identification_key,
    send_sms
)

# -------------------------------------------------------------------------
# 1) FETCH HTML Function
# -------------------------------------------------------------------------
async def fetch_bridgebio_html():
    """
    Returns the BridgeBio pipeline URL.
    You can later call fetch_with_zyte() on this URL 
    to get the actual HTML content for BridgeBio's pipeline page.
    """
    try:
        url = "https://bridgebio.com/pipeline/"
        return url
    except Exception as e:
        logging.error(f"Error fetching BridgeBio pipeline URL: {e}")
        return None


# -------------------------------------------------------------------------
# 2) PROCESS HTML Function
# -------------------------------------------------------------------------
async def process_bridgebio_html(html_content):
    """
    Parses BridgeBio's pipeline HTML and returns a list of serialized MasterTable objects.
    Uses scraping logic and calls clean_text(...) and clean_phase(...).
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for BridgeBio pipeline.")
            # Optional: Send an SMS notification if there's no content
            send_sms(
                phone_number="9144334333",
                message="BridgeBio script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # -----------------------------------------------
        # Scraping logic (modified from our working script)
        # -----------------------------------------------
        pipeline_data = []

        # For each <section class="pipeline-content">
        sections = soup.find_all('section', class_='pipeline-content')
        for section in sections:
            # pipeline_category --> "therapeutic_area"
            therapeutic_area = section.get('id') or "Uncategorized"
            therapeutic_area = clean_text(therapeutic_area)  # Clean up the area text

            listings = section.find_all('div', class_='listing')
            for listing in listings:
                expanders = listing.find_all('div', class_='flex-row expander pipeline__expander')

                for expander in expanders:
                    # Phase: we'll do a clean_phase on the attribute
                    phase = None
                    progress_bar = expander.find('div', class_='progress-bar')
                    if progress_bar:
                        raw_phase = progress_bar.get('data-phase', "")
                        phase = clean_phase(raw_phase)

                    # Treatment name
                    program_name = None
                    title_h6 = expander.find('h6', class_='title')
                    if title_h6:
                        program_name = clean_text(title_h6.get_text(strip=True))

                    # Short summary (comment)
                    comment = None
                    summary_div = expander.find('div', class_='flex-column two-three')
                    if summary_div:
                        comment = clean_text(summary_div.get_text(strip=True))

                    # We want the block that holds disease, genetic source, prevalence, modality
                    # skipping program-history or learn-more blocks
                    expand_blocks = expander.find_all('div', class_='flex-row expand')
                    data_block = None
                    for block in expand_blocks:
                        block_classes = block.get('class', [])
                        if 'program-history' in block_classes or 'learn-more' in block_classes:
                            continue
                        data_block = block
                        break

                    indication = None
                    target = None
                    prevalence = None
                    modality = None

                    if data_block:
                        columns = data_block.find_all('div', class_='flex-column')
                        for col in columns:
                            label_h6 = col.find('h6')
                            value_p = col.find('p')
                            if not label_h6 or not value_p:
                                continue

                            label = label_h6.get_text(strip=True).lower()
                            value = clean_text(value_p.get_text(strip=True))

                            if "disease" in label:
                                indication = value
                            elif "genetic source" in label:
                                target = value
                            elif "estimated prevalence" in label:
                                # rename to prevalence
                                prevalence = value
                            elif "modality" in label:
                                modality = value

                    # Program summary notes
                    notes = None
                    history_block = expander.find('div', class_='flex-row expand program-history')
                    if history_block:
                        p_tag = history_block.find('p')
                        if p_tag:
                            notes = clean_text(p_tag.get_text(strip=True))

                    # Build the dictionary
                    record = {
                        "therapeutic_area": therapeutic_area,
                        "treatment_name": program_name or "",
                        "phase": phase or "",
                        "indication": indication or "",
                        "target": target or "",
                        "prevalence": prevalence or "",
                        "modality": modality or "",
                        "comment": comment or "",
                        "notes": notes or ""
                    }
                    pipeline_data.append(record)

        # -----------------------------------------------
        # Convert to MasterTable Objects
        # -----------------------------------------------
        final_results = []
        processed_keys = set()
        date_scraped = datetime.now(timezone.utc)

        for record in pipeline_data:
            therapeutic_area = record["therapeutic_area"]
            treatment_name = record["treatment_name"]
            phase = record["phase"]
            indication = record["indication"]
            target = record["target"]
            prevalence = record["prevalence"]
            modality = record["modality"]
            comment = record["comment"]
            notes = record["notes"]

            # Build an identification key
            identification_key = generate_identification_key(
                "BridgeBio", treatment_name, indication, phase
            )

            # Build your multilingual data fields
            area_trans = MultilingualData()
            area_trans.add_translation("en", therapeutic_area)

            tname_trans = MultilingualData()
            tname_trans.add_translation("en", treatment_name)

            phase_trans = MultilingualData()
            phase_trans.add_translation("en", phase)

            indication_trans = MultilingualData()
            indication_trans.add_translation("en", indication)

            target_trans = MultilingualData()
            target_trans.add_translation("en", target)

            prevalence_trans = MultilingualData()
            prevalence_trans.add_translation("en", prevalence)

            modality_trans = MultilingualData()
            modality_trans.add_translation("en", modality)

            comment_trans = MultilingualData()
            comment_trans.add_translation("en", comment)

            notes_trans = MultilingualData()
            notes_trans.add_translation("en", notes)

            # Build Collections if needed
            area_coll = MultilingualDataCollection()
            area_coll.add_data(area_trans)

            tname_coll = MultilingualDataCollection()
            tname_coll.add_data(tname_trans)

            phase_coll = MultilingualDataCollection()
            phase_coll.add_data(phase_trans)

            indication_coll = MultilingualDataCollection()
            indication_coll.add_data(indication_trans)

            target_coll = MultilingualDataCollection()
            target_coll.add_data(target_trans)

            prevalence_coll = MultilingualDataCollection()
            prevalence_coll.add_data(prevalence_trans)

            modality_coll = MultilingualDataCollection()
            modality_coll.add_data(modality_trans)

            comment_coll = MultilingualDataCollection()
            comment_coll.add_data(comment_trans)

            notes_coll = MultilingualDataCollection()
            notes_coll.add_data(notes_trans)

            # Compose a unique key to avoid duplicates
            unique_key = (
                therapeutic_area, treatment_name, phase, indication,
                target, prevalence, modality, comment, notes
            )

            if unique_key in processed_keys:
                continue
            processed_keys.add(unique_key)

            # Build the MasterTable object
            master_record = MasterTable(
                company_name="BridgeBio",
                therapeutic_area=area_coll.get_collection_as_json(),
                treatment_name=tname_coll.get_collection_as_json(),
                indication=indication_coll.get_collection_as_json(),
                phase=phase_coll.get_collection_as_json(),
                target=target_coll.get_collection_as_json(),
                modality=modality_coll.get_collection_as_json(),
                prevalence=prevalence_coll.get_collection_as_json(),
                comment=comment_coll.get_collection_as_json(),
                notes=notes_coll.get_collection_as_json(),
                date_scraped=date_scraped,
                identification_key=identification_key
            )

            final_results.append(master_record.__dict__)

        logging.info(f"Processed {len(final_results)} treatments for BridgeBio.")
        return final_results

    except Exception as e:
        logging.error(f"An error occurred scraping BridgeBio's Pipeline: {e}")
        send_sms(
            phone_number="9144334333",
            message=f"Error in BridgeBio script: {e}. Please investigate!"
        )
        return []
