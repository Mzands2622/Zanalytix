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
import asyncio


async def fetch_daiichi_html():
    """
    Fetches the Daiichi Sankyo pipeline URL via Zyte.
    """
    try:
        url = 'https://www.daiichisankyo.com/rd/pipeline/'
        return url
    except Exception as e:
        logging.error(f"Error fetching Daiichi Sankyo HTML: {e}")
        return None


def get_last_updated_date(soup):
    """
    Find the last updated date from the Pipeline Chart header.
    """
    date_wrapper = soup.find("div", class_="h2Wrapper")
    if date_wrapper:
        date_text = date_wrapper.find("p", class_="txtXsmall")
        if date_text:
            return date_text.get_text(strip=True).replace("* ", "")
    return ""


async def process_daiichi_html(html_content):
    """
    Parses the Daiichi Sankyo pipeline HTML and returns a list of serialized MasterTable objects.
    """
    try:
        if not html_content:
            logging.warning("No HTML content received for Daiichi Sankyo pipeline.")
            send_sms(
                phone_number="9144334333", 
                message="Daiichi Sankyo script returned no HTML content. Please investigate!"
            )
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        
        date_last_updated = get_last_updated_date(soup)
        date_last_updated = clean_text(date_last_updated)

        treatments = []
        processed_treatments = set()

        def parse_footnotes(soup, container_id):
            """
            Parse footnotes from the specified container.
            """
            notes_map = {}
            container = soup.find("div", {"id": container_id})
            if not container:
                return notes_map

            p_tag = container.find("p", class_="txtNote")
            if not p_tag:
                return notes_map

            # Process text content
            text_content = p_tag.get_text(separator="\n")
            lines = [line.strip() for line in text_content.split("\n") if line.strip()]

            # Look for ※1 notation
            for line in lines:
                if line.startswith("※1"):
                    notes_map["※1"] = line.split("※1", 1)[1].strip()

                # Look for abbreviation lines (containing multiple ":" and ",")
                elif "," in line and ":" in line and not line.startswith("："):
                    parts = [part.strip() for part in line.split(",")]
                    for part in parts:
                        if ":" in part:
                            abbrev, definition = [x.strip() for x in part.split(":", 1)]
                            if abbrev and definition:
                                notes_map[abbrev] = definition

            # Process images and their descriptions
            for img in p_tag.find_all("img"):
                src = img.get("src", "")
                file_name = src.split("/")[-1].split("?")[0]
                next_sibling = img.next_sibling
                if next_sibling:
                    description = next_sibling.strip().lstrip("：")
                    notes_map[file_name] = description

            # Find green square notation
            green_square = p_tag.find("span", style=lambda x: x and "#00b050" in x)
            if green_square:
                current = green_square
                while current:
                    current = current.next_sibling
                    if isinstance(current, str) and "：" in current:
                        text = current.split("：", 1)[1].strip()
                        notes_map["green_square"] = text
                        break

            return notes_map

        def build_phase_map(soup, container_id):
            """
            Build phase mapping from tab structure.
            """
            phase_map = {}
            container_div = soup.find("div", {"id": container_id})
            if not container_div:
                return phase_map

            ul = container_div.find("ul", class_="ulList_vertical")
            if not ul:
                return phase_map

            for li in ul.find_all("li"):
                a_tag = li.find("a")
                if a_tag and a_tag.has_attr("href"):
                    href_val = a_tag["href"].lstrip("#")
                    text_val = a_tag.get_text(strip=True)
                    text_val = text_val.split("(")[0].strip()  # Remove parenthetical text
                    phase_map[href_val] = text_val
            return phase_map

        def parse_cells(td):
            """
            Parse individual table cells.
            """
            text = td.get_text(separator="\n", strip=True)
            lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
            full_text = " ".join(lines)

            # Extract region from parentheses at start
            region = ""
            if lines:
                match = re.match(r"^\(([^)]+)\)", lines[0])
                if match:
                    region = match.group(1).strip()

            # Extract study name
            study_regex = r"(DESTINY-\S+|TROPION-\S+|IDeate-\S+|HERTHENA-\S+)"
            study_match = re.search(study_regex, full_text, re.IGNORECASE)
            study_name = study_match.group(0) if study_match else ""

            # Get the cell's style for green border detection
            style_attr = td.get("style", "") or ""
            
            # Find image references
            images_found = []
            for img_tag in td.find_all("img"):
                img_src = img_tag.get("src", "")
                file_name = img_src.split("/")[-1].split("?")[0]
                images_found.append(file_name)

            return {
                "lines": lines,
                "full_text": full_text,
                "region": region,
                "study_name": study_name,
                "notes": [],
                "td_style": style_attr,
                "images": images_found,
                "phase": ""
            }

        # Get footnotes from both sections
        footnotes_5dxd = parse_footnotes(soup, "dnn_ctr1324_ContentPane")
        footnotes_nextwave = parse_footnotes(soup, "dnn_ctr1333_ContentPane")
        all_footnotes = {**footnotes_5dxd, **footnotes_nextwave}

        def attach_footnotes(entry):
            """
            Attach relevant footnotes to an entry.
            """
            text = entry["full_text"]
            
            # Check for abbreviations
            for foot_key, foot_val in all_footnotes.items():
                # Handle abbreviations
                if foot_key not in ["※1", "green_square"] and not foot_key.endswith(".png"):
                    if re.search(rf'\b{re.escape(foot_key)}\b', text):
                        entry["notes"].append(f"{foot_key}: {foot_val}")

            # Check for *1 notation
            if "*1" in text or any("*1" in line for line in entry["lines"]):
                if "※1" in all_footnotes:
                    entry["notes"].append(all_footnotes["※1"])

            # Check for image references
            for img_file in entry["images"]:
                if img_file in all_footnotes:
                    entry["notes"].append(all_footnotes[img_file])

            # Check for green border
            if "border-color: #00b050" in entry["td_style"] and "green_square" in all_footnotes:
                entry["notes"].append(all_footnotes["green_square"])

        # Parse pipeline sections
        phase_map_5dxd = build_phase_map(soup, "dnn_ctr1318_ViewTabs_pnlTabs")
        phase_map_next_wave = build_phase_map(soup, "dnn_ctr1325_ViewTabs_pnlTabs")

        entries = []
        for phase_map in [phase_map_5dxd, phase_map_next_wave]:
            for tab_div_id, phase_name in phase_map.items():
                tab_div = soup.find("div", {"id": tab_div_id})
                if not tab_div:
                    continue
                    
                table = tab_div.find("table")
                if not table:
                    continue

                for row in table.find_all("tr"):
                    for td in row.find_all("td"):
                        cell_info = parse_cells(td)
                        if cell_info["full_text"]:
                            cell_info["phase"] = phase_name
                            attach_footnotes(cell_info)  # Attach footnotes here
                            entries.append(cell_info)

        # Process entries into MasterTable records
        for entry in entries:
            # Clean and prepare data
            name = clean_text(entry['full_text'])
            phase = clean_phase(entry['phase'])
            study = clean_text(entry['study_name'])
            region = clean_text(entry['region'])
            notes = " | ".join([clean_text(note) for note in entry['notes']])
            lines = [clean_text(line) for line in entry["lines"]]

            # Skip entries missing required fields
            if not name:
                logging.warning("Skipping entry due to missing name.")
                continue

            # Generate identification key
            identification_key = generate_identification_key(
                "Daiichi Sankyo",
                name
            )

            # Build multilingual data objects
            name_translator = MultilingualData()
            phase_translator = MultilingualData()
            study_translator = MultilingualData()
            region_translator = MultilingualData()
            notes_translator = MultilingualData()
            lines_translator = MultilingualData()
            date_last_updated_translator = MultilingualData()

            name_translator.add_translation("en", name)
            phase_translator.add_translation("en", phase)
            study_translator.add_translation("en", study)
            region_translator.add_translation("en", region)
            notes_translator.add_translation("en", notes)
            lines_translator.add_translation("en", lines)
            date_last_updated_translator.add_translation("en", date_last_updated)

            name_collection = MultilingualDataCollection()
            phase_collection = MultilingualDataCollection()
            study_collection = MultilingualDataCollection()
            region_collection = MultilingualDataCollection()
            notes_collection = MultilingualDataCollection()
            lines_collection = MultilingualDataCollection()
            date_last_updated_collection = MultilingualDataCollection()

            name_collection.add_data(name_translator)
            phase_collection.add_data(phase_translator)
            study_collection.add_data(study_translator)
            region_collection.add_data(region_translator)
            notes_collection.add_data(notes_translator)
            lines_collection.add_data(lines_translator)
            date_last_updated_collection.add_data(date_last_updated_translator)

            # Create unique key for deduplication
            treatment_key = (name, phase, notes)

            # Create MasterTable record if not duplicate
            if treatment_key not in processed_treatments:
                master_record = MasterTable(
                    company_name="Daiichi Sankyo",
                    treatment_name=name_collection.get_collection_as_json(),
                    phase=phase_collection.get_collection_as_json(),
                    study=study_collection.get_collection_as_json(),
                    country=region_collection.get_collection_as_json(),
                    date_scraped=datetime.now(timezone.utc),
                    identification_key=identification_key,
                    notes=notes_collection.get_collection_as_json(),
                    backup_lines=lines_collection.get_collection_as_json(),
                    date_last_changed=date_last_updated_collection.get_collection_as_json()
                )

                treatments.append(master_record.__dict__)
                processed_treatments.add(treatment_key)

        logging.info(f"Processed {len(treatments)} treatments for Daiichi Sankyo.")
        return treatments

    except Exception as e:
        logging.error(f"An error occurred scraping Daiichi Sankyo Pipeline: {e}")
        send_sms(
            phone_number="9144334333", 
            message=f"Error in Daiichi Sankyo script: {e}. Please investigate!"
        )
        return []