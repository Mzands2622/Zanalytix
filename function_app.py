import azure.functions as func
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import pyodbc
import requests
import re
from cleanup_phase import clean_phase
from cleanup_text import clean_text
import json
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
import openai
import smtplib
from twilio.rest import Client
import asyncio
import aiohttp
import importlib
from azure.storage.queue import QueueClient
import base64
import sys
import json
from requests.auth import HTTPBasicAuth
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
import os
import copy


# Set up environment variables
load_dotenv()

server = os.getenv("SERVER")
database = os.getenv("DATABASE")
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
driver = os.getenv("DRIVER")

CONNECTION_STRING = os.getenv("CONNECTION_STRING")

openai_api_key = os.getenv("OPENAI_API_KEY")


class MasterTable:
    def __init__(self, company_name="Null", therapeutic_area="Null", treatment_name="Null", target="Null", type_of_molecule="Null",
                 indication="Null", phase="Null", date_last_changed="Null", date_scraped="Null",
                 identification_key="Null", modality="Null", brand_name="Null", filing_date="Null",
                 submission_type="Null", notes="Null", disease_area="Null", phase_commencement_date="Null",
                 generic_name="Null", project_type="Null", managed_by="Null", partner="Null", comment="Null",
                 country="Null", study="Null", ndc="Null", size="Null", strength="Null", source_id="Null", treatment_alias="Null",
                 approval_date="Null", approval_type="Null", major_market_status="Null", status_change="Null", 
                 line_extension="Null", reason_for_discontinuation="Null", partner_images="Null",
                 prevalence="Null", backup_lines="Null", products_count="Null", research_development_percentage="Null",
                 regulatory_submission_percentage="Null", domain="Null", line_of_therapy="Null", regimen="Null"):
        self.Company_Name = company_name
        self.Therapeutic_Area = therapeutic_area
        self.Treatment_Name = treatment_name
        self.Target = target
        self.Type_of_Molecule = type_of_molecule
        self.Indication = indication
        self.Phase = phase
        self.Date_Last_Changed = date_last_changed
        self.Date_Scraped = date_scraped
        self.Identification_Key = identification_key
        self.Modality = modality
        self.Brand_Name = brand_name
        self.Filing_Date = filing_date
        self.Submission_Type = submission_type
        self.Notes = notes
        self.Disease_Area = disease_area
        self.Phase_Commencement_Date=phase_commencement_date
        self.Generic_Name=generic_name
        self.Project_Type=project_type
        self.Managed_By=managed_by
        self.Partner=partner
        self.Comment=comment
        self.Country=country
        self.NDC=ndc
        self.Size=size
        self.Strength = strength
        self.Study = study
        self.SourceID = source_id
        self.Treatment_Alias = treatment_alias
        self.Approval_Date = approval_date
        self.Approval_Type = approval_type
        self.Major_Market_Status=major_market_status
        self.Status_Change=status_change
        self.Line_Extension=line_extension
        self.Reason_For_Discontinuation=reason_for_discontinuation
        self.Partner_Images=partner_images
        self.Prevalence=prevalence
        self.Backup_Lines=backup_lines
        self.Products_Count=products_count
        self.Research_Development_Percentage=research_development_percentage
        self.Regulatory_Submission_Percentage=regulatory_submission_percentage
        self.Domain=domain
        self.Line_Of_Therapy=line_of_therapy
        self.Regimen=regimen

async def fetch_with_zyte(url):
    zyte_api_key = os.getenv("ZYTE_API_KEY")
    
    # Define the request parameters
    request_params = {
        "url": url,
        "browserHtml": True,
        "actions": [
            {"action": "scrollBottom"},
            {"action": "waitForTimeout", "timeout": 15},
        ]
    }

    # Asynchronously make the API request using aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.zyte.com/v1/extract",
            auth=aiohttp.BasicAuth(zyte_api_key, ''),
            json=request_params
        ) as response:
            if response.status == 200:
                api_response = await response.json()
                browser_html = api_response.get("browserHtml")
                return browser_html
            else:
                print(f"Failed to retrieve HTML for {url}. Status code: {response.status}")
                text = await response.text()
                print("Response:", text)
                return None


class MultilingualData:
    def __init__(self, data=None):
        if data is None:
            self.data = {}
        else:
            self.data = data

    def add_translation(self, language, value):
        self.data[language] = value

    def get_translations_as_dict(self):
        return self.data

    def has_translation(self, language):
        return language in self.data

    def translate_and_add(self, translation_func):
        if 'en' in self.data:
            logging.info("English translation already exists. No translation needed.")
            return None  # No need to return a list

        source_lang = next(iter(self.data))
        source_text = self.data[source_lang]
        translated_text = translation_func(source_text, source_lang, 'en')
        return {'en': translated_text}  # Return a dictionary directly
    

class MultilingualDataCollection:
    def __init__(self):
        self.collection = []

    def add_data(self, multilingual_data):
        if isinstance(multilingual_data, MultilingualData):
            self.collection.append(multilingual_data.get_translations_as_dict())

    def add_translations(self, translations):
        for translation in translations:
            if isinstance(translation, MultilingualData):
                self.add_data(translation)

    def get_collection_as_json(self):
        return json.dumps(self.collection, ensure_ascii=False)

    def find_by_language_and_text(self, language, text):
        return [data for data in self.collection if data.get(language) == text]

    def sort_by_language(self, language):
        self.collection.sort(key=lambda data: data.get(language, ""))


def translate_text(text, source_lang='fr', target_lang='en'):
    translated_text = call_translation_api(text, source_lang, target_lang)
    return translated_text

def call_translation_api(text, source_lang, target_lang):
    return f"{text}"


def process_and_translate_all_entries(treatment_data, cursor, treatment_key):
    """
    1) Sorts every record by date (earliest -> latest).
    2) For each entry, translates all fields except "Phase", 
       reusing older 'en' translations if available.
    3) For the final (newest) entry only: we preserve its newly-scraped Phase
       and, if needed, translate it to 'en'.
    4) Updates the DB with the fully translated treatment_data.
    """

    alert_phone_number = "9144334333"  # for debug SMS, if desired

    try:
        # 0) Basic structure checks
        if not isinstance(treatment_data, list) or not all(isinstance(item, dict) for item in treatment_data):
            logging.error(f"[{treatment_key}] Unexpected structure: {treatment_data}")
            return

        # 1) Sort the list by date key ascending
        treatment_data_sorted = sort_treatment_data_by_key(treatment_data)

        # 2) We'll keep track of "best known 'en' data" for each field to reuse
        best_en_for_field = {}

        # Fields to translate (excluding "Phase")
        fields_to_translate = [
            "Company_Name", "Therapeutic_Area", "Treatment_Name", "Target", "Type_Of_Molecule",
            "Indication", "Date_Last_Changed", "Date_Scraped", "Identification_Key",
            "Modality", "Brand_Name", "Filing_Date", "Submission_Type", "Notes", "Disease_Area",
            "Phase_Commencement_Date", "Generic_Name", "Project_Type", "Managed_By", "Partner",
            "Comment", "Country", "Study", "NDC", "Size", "Strength", "Treatment_Alias",
            "Approval_Date", "Approval_Type", "Major_Market_Status", "Status_Change", "Line_Extension",
            "Reason_For_Discontinuation", "Prevalence", "Backup_Lines", "Domain", "Line_Of_Therapy",
            "Regimen"
        ]

        # 3) Iterate through entries in ascending date
        for idx, record in enumerate(treatment_data_sorted):
            date_key, details = list(record.items())[0]

            logging.info(f"[{treatment_key}] Processing date={date_key}")

            # ---------------------
            # A) Translate fields
            # ---------------------
            for field in fields_to_translate:
                if field not in details:
                    continue

                current_field_data = safe_json_loads(details[field])
                if not current_field_data:
                    logging.info(f"  └─ Field '{field}' empty => skipping translation.")
                    continue

                # If we have best_en_for_field[field], see if there's an existing 'en'
                older_data = best_en_for_field.get(field, [])
                found_en_older = any(isinstance(d, dict) and "en" in d for d in older_data)

                # Check if current also already has 'en'
                found_en_current = any(isinstance(d, dict) and "en" in d for d in current_field_data)

                if found_en_current:
                    # If the current has 'en' already, store that as our "best" for the future
                    best_en_for_field[field] = current_field_data
                    logging.info(f"  └─ Field '{field}': current record already has 'en'. Reusing it.")
                else:
                    # Current doesn't have 'en'
                    if found_en_older:
                        # We do have an older record with 'en': reuse it
                        logging.info(f"  └─ Reusing older 'en' for field '{field}'.")
                        current_field_data = older_data
                    else:
                        # We need to translate from scratch
                        logging.info(f"  └─ Translating new '{field}' for date={date_key}, key={treatment_key}.")
                        # For example, call your logic that translates the 1st dict's text
                        if isinstance(current_field_data, list) and current_field_data:
                            md = MultilingualData(current_field_data[0])
                            new_translation = md.translate_and_add(translate_text)
                            if new_translation:
                                current_field_data.append(new_translation)

                    # Update best_en_for_field and the record
                    best_en_for_field[field] = current_field_data
                    details[field] = json.dumps(current_field_data, ensure_ascii=False)

            # ---------------------
            # B) For the final entry only, preserve & translate Phase
            # ---------------------
            # If you ONLY want the final entry to keep its newly scraped Phase, do this:
            if idx == len(treatment_data_sorted) - 1:  # final entry
                original_phase = details.get("Phase")
                if original_phase:
                    # Overwrite any previously merged Phase with the newly scraped one
                    details["Phase"] = original_phase

                    # If that newly scraped Phase has no 'en', then translate
                    phase_list = safe_json_loads(original_phase)
                    if phase_list and not any("en" in d for d in phase_list if isinstance(d, dict)):
                        logging.info(f"  └─ Translating newly-scraped Phase in final record for {treatment_key}.")
                        md_phase = MultilingualData(phase_list[0])
                        new_phase_translation = md_phase.translate_and_add(translate_text)
                        if new_phase_translation:
                            phase_list.append(new_phase_translation)

                        # Re-store the Phase
                        details["Phase"] = json.dumps(phase_list, ensure_ascii=False)

        # 4) Save the updated, sorted data back into the DB
        updated_json = json.dumps(treatment_data_sorted, ensure_ascii=False)
        update_query = "UPDATE Revised_MasterTable SET Treatment_Data = ? WHERE Treatment_Key = ?"
        cursor.execute(update_query, (updated_json, treatment_key))

        logging.info(f"✅ Successfully updated all translations for {treatment_key} (multi-entry).")

    except Exception as e:
        logging.error(f"❌ Error in process_and_translate_all_entries for {treatment_key}: {e}")
        raise

def safe_json_loads(field_value):
    # Handles "Null" strings and empty values gracefully
    if not field_value or field_value == "Null":
        return []  # Default to empty list
    try:
        return json.loads(field_value)  # Parse valid JSON
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON format: {field_value}")
        return []  # Return empty list on error

def generate_identification_key(company, treatment_name=None, therapeutic_area=None, indication=None, target=None):
    parts = []
    
    if company is not None:
        parts.append(str(company))
    if treatment_name is not None:
        parts.append(str(treatment_name))
    if therapeutic_area is not None:
        parts.append(str(therapeutic_area))
    if indication is not None:
        parts.append(str(indication))
    if target is not None:
        parts.append(str(target))

    return "_".join(parts).replace(" ", "_")




def round_down_time(dt=None, round_to=5):
    """Round down a datetime object to the nearest 'round_to' minute increment."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    minutes = (dt.minute // round_to) * round_to
    return dt.replace(minute=minutes, second=0, microsecond=0)


###############################################################################
# Function 1: ScrapeHTMLTrigger
###############################################################################
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
@app.function_name(name="ScrapeHTMLTrigger")
@app.route(route="scrape_html_trigger")
async def scrape_html_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Starting HTML collection...')

    # Step 0: Set up your Azure Queue for scraping tasks
    queue_client = QueueClient.from_connection_string(CONNECTION_STRING, "scraping-tasks")

    # Step 1: Connect to SQL
    connection_string = f"DRIVER={driver};SERVER={server};PORT=1433;DATABASE={database};UID={username};PWD={password}"
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()

    try:
        # (1A) Ensure ScrapingTaskTracker table exists
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ScrapingTaskTracker')
            BEGIN
                CREATE TABLE ScrapingTaskTracker (
                    DateKey DATE PRIMARY KEY,
                    TotalTasks INT,
                    RemainingTasks INT
                )
            END
        """)
        conn.commit()

        # 2) Retrieve scheduled tasks for the current (rounded) time
        current_time = round_down_time(datetime.now(timezone.utc), round_to=5)
        logging.info(f"🕒 Current system UTC time: {current_time}")

        cursor.execute("SELECT Scraping_Objects FROM Calendar WHERE Time = ?", (current_time,))
        row = cursor.fetchone()

        if not row:
            logging.info("No scraping tasks scheduled.")
            return func.HttpResponse("No scraping tasks scheduled.", status_code=204)

        # 3) (Optional) Auto-add 30 hours if we’re at the last row in Calendar
        scraping_objects_json = row[0]
        cursor.execute("SELECT MAX(Time) FROM Calendar;")
        last_time_row = cursor.fetchone()
        if last_time_row and last_time_row[0]:
            max_time_in_calendar = last_time_row[0]
            if current_time == max_time_in_calendar:
                logging.info("We are at the last scheduled row. Auto-adding 30 more hours...")
                for i in range(1, 31):  
                    new_time = max_time_in_calendar + timedelta(hours=i)
                    cursor.execute("""
                        INSERT INTO Calendar (Time, Scraping_Objects, [Check])
                        VALUES (?, ?, 0)
                    """, (new_time, scraping_objects_json))
                conn.commit()
        else:
            logging.warning("Could not retrieve MAX(Time) from Calendar, or table empty.")

        # 4) Count the tasks
        scraping_objects = json.loads(scraping_objects_json)
        num_tasks = len(scraping_objects)
        logging.info(f"Number of scraping tasks: {num_tasks}")

        # 5) Update or Insert SCRAPING counters for today's date
        date_key = current_time.date()
        cursor.execute("SELECT * FROM ScrapingTaskTracker WHERE DateKey = ?", (date_key,))
        tracker = cursor.fetchone()
        if tracker:
            cursor.execute("""
                UPDATE ScrapingTaskTracker
                SET TotalTasks = ?, RemainingTasks = ?
                WHERE DateKey = ?
            """, (num_tasks, num_tasks, date_key))
        else:
            cursor.execute("""
                INSERT INTO ScrapingTaskTracker (DateKey, TotalTasks, RemainingTasks)
                VALUES (?, ?, ?)
            """, (date_key, num_tasks, num_tasks))
        conn.commit()

        # 6) Enqueue each scraping task
        for obj in scraping_objects:
            object_code = obj['objectCode']
            logging.info(f"Fetching URL for {object_code}...")

            module = importlib.import_module(f"{object_code}")
            fetch_function = getattr(module, f"fetch_{'_'.join(object_code.split('_')[:-1])}_html")
            url = await fetch_function()

            if not url:
                logging.warning(f"No URL found for {object_code}. Skipping.")
                continue

            task = {"objectCode": object_code, "url": url}
            message = base64.b64encode(json.dumps(task).encode("utf-8")).decode("utf-8")
            queue_client.send_message(message)
            logging.info(f"Added task for {object_code} to the queue.")

        return func.HttpResponse("Tasks queued successfully.", status_code=200)

    except Exception as e:
        logging.error(f"Error during HTML collection: {e}")
        alert_phone_number = "9144334333"
        alert_message = f"Alert: '{e}'"
        send_sms(alert_phone_number, alert_message)
        return func.HttpResponse(f"Error: {e}", status_code=500)
    finally:
        cursor.close()
        conn.close()

@app.function_name(name="CheckMissingNotificationsTrigger")
@app.route(route="missing_notifications_check")
async def check_missing_notifications_trigger(req: func.HttpRequest) -> func.HttpResponse:
    try:
        connection_string = (
            f"DRIVER={driver};SERVER={server};PORT=1433;"
            f"DATABASE={database};UID={username};PWD={password}"
        )
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # Diagnostic counts
        cursor.execute("""
            SELECT COUNT(*) as total_treatments
            FROM Revised_MasterTable
            WHERE ISJSON(Treatment_Data) = 1;
        """)
        total = cursor.fetchone()[0]
        logging.info(f"Total treatments in database: {total}")

        cursor.execute("""
            SELECT COUNT(*) as multi_entry_treatments
            FROM Revised_MasterTable
            WHERE ISJSON(Treatment_Data) = 1
            AND (SELECT COUNT(*) FROM OPENJSON(Treatment_Data)) >= 2;
        """)
        multi_entries = cursor.fetchone()[0]
        logging.info(f"Treatments with 2 or more entries: {multi_entries}")

        # Main query with corrected App_Notification check
        query = """
        WITH NumberedRows AS (
            SELECT
                rm.Treatment_Key,
                rm.Treatment_Data,
                CAST(entry.[key] as INT) as idx,
                entry.[value] as val
            FROM Revised_MasterTable rm
            CROSS APPLY OPENJSON(rm.Treatment_Data) entry
            WHERE ISJSON(rm.Treatment_Data) = 1
            AND (SELECT COUNT(*) FROM OPENJSON(rm.Treatment_Data)) >= 2
        ),
        LastEntries AS (
            -- Get only the latest entry for each treatment
            SELECT 
                Treatment_Key,
                Treatment_Data,
                idx,
                val
            FROM NumberedRows nr1
            WHERE idx = (
                SELECT MAX(idx)
                FROM NumberedRows nr2
                WHERE nr2.Treatment_Key = nr1.Treatment_Key
            )
        )
        SELECT DISTINCT
            Treatment_Key,
            Treatment_Data
        FROM LastEntries le
        CROSS APPLY OPENJSON(le.val) nested -- This gets inside the date object
        WHERE NOT EXISTS (
            SELECT 1
            FROM OPENJSON(nested.[value]) fields -- This looks at the fields inside that date object
            WHERE fields.[key] = 'App_Notification'
        );
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        alert_phone_number = "9144334333"
        alert_message = f"Fetched {len(rows)} treatments missing final App_Notification."
        send_sms(alert_phone_number, alert_message)

        if not rows:
            logging.info("No missing notifications found.")
            return func.HttpResponse("No missing notifications found.", status_code=200)

        # Process found rows
        processed_count = 0
        for row in rows:
            treatment_key = row[0]
            tdata_str = row[1]

            try:
                tdata_json = json.loads(tdata_str)
                if not isinstance(tdata_json, list) or len(tdata_json) < 2:
                    logging.warning(f"Skipping {treatment_key}: Insufficient entries in treatment data")
                    continue

                task_data = {
                    "treatment_key": treatment_key,
                    "treatment_data": tdata_json
                }

                enqueue_for_comparison(task_data)
                processed_count += 1
                logging.info(f"Re-queued for comparison: {treatment_key}")
            except json.JSONDecodeError as e:
                logging.error(f"Malformed JSON for {treatment_key}: {e}")
                continue

        result_message = f"Re-queued {processed_count} out of {len(rows)} found treatments for comparison."
        return func.HttpResponse(result_message, status_code=200)

    except Exception as e:
        error_msg = f"Error in CheckMissingNotificationsTrigger: {e}"
        logging.error(error_msg)
        return func.HttpResponse(error_msg, status_code=500)
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
        logging.info("Finished CheckMissingNotificationsTrigger.")

###############################################################################
# Function 2: ProcessQueueTrigger
###############################################################################
@app.function_name(name="ProcessQueueTrigger")
@app.queue_trigger(
    arg_name="msg",
    queue_name="scraping-tasks",
    connection="AzureWebJobsStorage"
)
async def process_queue_trigger(msg: func.QueueMessage) -> None:
    logging.info('Processing queue message...')

    # 1) Parse the queue message
    try:
        message_body = msg.get_body().decode('utf-8')
        decoded_body = json.loads(message_body)
        object_code = decoded_body.get("objectCode")
        url = decoded_body.get("url")

        if not object_code or not url:
            logging.error("Message missing objectCode or URL.")
            return

        logging.info(f"Processing task for: {object_code} with URL: {url}")
    except Exception as e:
        logging.error(f"Failed to parse message: {e}")
        return

    # 2) Fetch HTML content
    try:
        logging.info(f"Fetching HTML content for {object_code}...")
        html_content = await fetch_with_zyte(url)
        if not html_content:
            logging.error(f"Failed to fetch HTML content for {object_code}.")
            return
        logging.info(f"HTML content fetched successfully for {object_code}.")
        await save_html_to_table(html_content, object_code)
    except Exception as e:
        logging.error(f"Error fetching HTML content: {e}")
        return

    conn = None
    cursor = None

    try:
        # 3) Connect to SQL and load the processing function
        connection_string = f'DRIVER={driver};SERVER=tcp:{server};PORT=1433;DATABASE={database};UID={username};PWD={password}'
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        logging.info(f"Loading processing function for {object_code}")
        module = importlib.import_module(object_code)
        process_name = f"process_{'_'.join(object_code.split('_')[:-1])}_html"
        process_function = getattr(module, process_name)

        # 4) Process the HTML content into a list of treatments
        logging.info(f"Processing HTML content for {object_code}")
        treatments = await process_function(html_content)

        if not treatments:
            logging.warning(f"No treatments extracted for {object_code}.")
            alert_phone_number = "9144334333"
            alert_message = f"Alert: 'No treatments found for {object_code}. Please investigate!'"
            send_sms(alert_phone_number, alert_message)
            # Decrement tasks here, because no treatments still counts as "processed"
            try:
                date_key = datetime.now(timezone.utc).date()
                cursor.execute(
                    "UPDATE ScrapingTaskTracker SET RemainingTasks = RemainingTasks - 1 WHERE DateKey = ?",
                    (date_key,)
                )
                conn.commit()

                # check if that hits zero => maybe trigger translation
                cursor.execute("SELECT RemainingTasks FROM ScrapingTaskTracker WHERE DateKey = ?", (date_key,))
                row = cursor.fetchone()
                if row and row[0] == 0:
                    # Potentially call translation_queuing_trigger() or something
                    ...
            except Exception as e:
                logging.error(f"Error decrementing tasks: {e}")

            return

        # 5) Insert or update data in Revised_MasterTable
        for treatment in treatments:
            treatment_key = treatment.get('Identification_Key')
            if not treatment_key:
                logging.warning(f"Missing identification_key in treatment for {object_code}")
                continue

            # Add current time
            current_time = datetime.now(timezone.utc).strftime('%Y%m%d')
            new_data = {current_time: treatment}

            try:
                cursor.execute(
                    "SELECT Treatment_Data FROM Revised_MasterTable WHERE Treatment_Key = ?",
                    (treatment_key,)
                )
                existing_data = cursor.fetchone()

                if existing_data:
                    existing_json = json.loads(existing_data[0])
                    if not isinstance(existing_json, list):
                        existing_json = [existing_json]
                    existing_json.append(new_data)
                    cursor.execute(
                        "UPDATE Revised_MasterTable SET Treatment_Data = ? WHERE Treatment_Key = ?",
                        (json.dumps(existing_json, default=str), treatment_key)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO Revised_MasterTable (Company_Name, Treatment_Key, Treatment_Data) "
                        "VALUES (?, ?, ?)",
                        (object_code, treatment_key, json.dumps([new_data], default=str))
                    )
            except Exception as e:
                logging.error(f"Error processing treatment {treatment_key}: {e}")
                continue

        conn.commit()
        logging.info(f"Successfully processed and saved data for {object_code}")

        # 6) Decrement the ScrapingTaskTracker
        logging.info("Decrementing counter in ScrapingTaskTracker...")
        date_key = datetime.now(timezone.utc).date()
        cursor.execute(
            "UPDATE ScrapingTaskTracker SET RemainingTasks = RemainingTasks - 1 WHERE DateKey = ?",
            (date_key,)
        )
        conn.commit()

        # 7) If the new remaining count == 0 => trigger translation
        cursor.execute("SELECT RemainingTasks FROM ScrapingTaskTracker WHERE DateKey = ?", (date_key,))
        remaining_tasks = cursor.fetchone()[0]
        logging.info(f"Remaining tasks: {remaining_tasks}")

        if remaining_tasks == 0:
            try:
                cursor.execute(
                    "UPDATE ScrapingTaskTracker SET RemainingTasks = 0 WHERE DateKey = ?",
                    (date_key,)
                )
                conn.commit()
                logging.info("Counter reset to 0 in ScrapingTaskTracker.")

                logging.info("All tasks processed. Triggering TranslationQueuingTrigger...")
                try:
                    artificial_insertion_queuing_trigger()
                    alert_phone_number = "9144334333"
                    alert_message = "Translation process started successfully for this hour!"
                    send_sms(alert_phone_number, alert_message)
                    logging.info("Translation process started successfully!")
                except Exception as e:
                    logging.error(f"Error during translation process: {e}")

            except Exception as e:
                logging.error(f"Error while resetting counter or triggering translation: {e}")

    except Exception as e:
        logging.error(f"Error processing queue message: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

            

async def save_html_to_table(html_content, company_name):
    """A placeholder function that does nothing but log a success message."""
    logging.info(f"Skipped saving HTML for {company_name}. Function was called but does nothing.")


def artificial_insertion_queuing_trigger():
    QUEUE_NAME = "artificial-insertion-tasks"

    try:
        logging.info("Connecting to Azure Queue for artificial insertion...")
        queue_client = QueueClient.from_connection_string(CONNECTION_STRING, QUEUE_NAME)
        logging.info("Queue connection established.")

        # Connect to Database
        logging.info("Connecting to the database for artificial insertion tasks...")
        connection_string = f"DRIVER={driver};SERVER={server};PORT=1433;DATABASE={database};UID={username};PWD={password}"
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        logging.info("Database connection established.")

        # 1) Ensure ArtificialInsertionTaskTracker table exists (already done in your code)
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ArtificialInsertionTaskTracker')
            BEGIN
                CREATE TABLE ArtificialInsertionTaskTracker (
                    DateKey DATE PRIMARY KEY,
                    TotalTasks INT,
                    RemainingTasks INT
                )
            END
        """)
        conn.commit()

        # 2) Select first-time treatments
        cursor.execute("SELECT Treatment_Key, Treatment_Data FROM Revised_MasterTable")
        rows = cursor.fetchall()
        first_time_keys = []
        
        for row in rows:
            tkey, tdata_raw = row
            try:
                tdata_json = json.loads(tdata_raw)
                if isinstance(tdata_json, list) and len(tdata_json) == 1:
                    first_time_keys.append(tkey)
            except json.JSONDecodeError:
                logging.error(f"Malformed JSON for {tkey}. Skipping.")
        
        if not first_time_keys:
            logging.info("No first-time treatments found. (You might call translation here.)")
            translation_queuing_trigger()
            return

        # 3) Set up date_key and track how many tasks
        date_key = datetime.now(timezone.utc).date()
        total_tasks = len(first_time_keys)

        # Insert/Update ArtificialInsertionTaskTracker
        cursor.execute("""
            IF EXISTS (SELECT * FROM ArtificialInsertionTaskTracker WHERE DateKey = ?)
                UPDATE ArtificialInsertionTaskTracker
                SET TotalTasks = ?, RemainingTasks = ?
                WHERE DateKey = ?
            ELSE
                INSERT INTO ArtificialInsertionTaskTracker (DateKey, TotalTasks, RemainingTasks)
                VALUES (?, ?, ?)
        """, (date_key, total_tasks, total_tasks, date_key, date_key, total_tasks, total_tasks))
        conn.commit()

        # 4) Enqueue messages with date_key
        for treatment_key in first_time_keys:
            message_data = {
                "treatment_key": treatment_key,
                "date_key": str(date_key)   # pass the date key here
            }
            encoded_message = base64.b64encode(json.dumps(message_data).encode("utf-8")).decode("utf-8")
            queue_client.send_message(encoded_message)
            logging.info(f"Queued artificial insertion task for {treatment_key} with date_key={date_key}")

        return func.HttpResponse("Artificial insertion tasks queued successfully.", status_code=200)

    except Exception as e:
        logging.error(f"Error in artificial_insertion_queuing_trigger: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
        logging.info("Closed DB connection for artificial insertion queuing.")


def translation_queuing_trigger():
    # Azure Queue Setup
    QUEUE_NAME = "translation-tasks"

    try:
        logging.info('Connecting to Azure Queue...')
        queue_client = QueueClient.from_connection_string(CONNECTION_STRING, QUEUE_NAME)
        logging.info('Azure Queue connection established.')

        # Connect to Database
        logging.info('Connecting to the database...')
        connection_string = f'DRIVER={driver};SERVER=tcp:{server};PORT=1433;DATABASE={database};UID={username};PWD={password}'
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        logging.info('Database connection established.')

        create_stream_table(conn)
        logging.info('Stream table setup complete.')

        # Query to find treatments needing translation
        logging.info('Fetching treatments requiring translation...')
        query = """
        WITH NumberedRows AS (
            SELECT 
                Treatment_Key,
                Treatment_Data,
                entry.[key],
                entry.[value]
            FROM Revised_MasterTable rm
            CROSS APPLY OPENJSON(Treatment_Data) entry
            WHERE ISJSON(Treatment_Data) = 1
            AND (SELECT COUNT(*) FROM OPENJSON(rm.Treatment_Data)) > 0
        ),
        LastEntry AS (
            SELECT 
                nr1.Treatment_Key,
                nr1.Treatment_Data,
                nr1.[value] as last_entry
            FROM NumberedRows nr1
            WHERE nr1.[key] = (
                SELECT MAX(nr2.[key])
                FROM NumberedRows nr2
                WHERE nr2.Treatment_Key = nr1.Treatment_Key
            )
        )
        SELECT 
            Treatment_Key,
            Treatment_Data
        FROM LastEntry le
        WHERE 
            le.last_entry IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM OPENJSON(le.last_entry) fields
                WHERE fields.[key] = 'App_Notification'
            );
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        logging.info(f'Fetched {len(rows)} treatments from the database.')

        if not rows:
            logging.info("No treatments found requiring translation.")
            return func.HttpResponse("No treatments found requiring translation.", status_code=204)

        # Queue tasks for translation
        for index, row in enumerate(rows):
            treatment_key = row[0]
            treatment_data = row[1]

            try:
                logging.debug(f"Processing row {index + 1}: Treatment Key = {treatment_key}")
                
                treatment_data_json = json.loads(treatment_data)
                logging.debug(f"Valid JSON for Treatment Key {treatment_key}.")
                
                # Create task metadata
                task = {
                    "treatment_key": treatment_key,
                    "treatment_data": treatment_data_json,
                    "languages": ["en", "fr"]
                }

                message = base64.b64encode(json.dumps(task).encode('utf-8')).decode('utf-8')
                queue_client.send_message(message)
                logging.info(f"Queued translation task for Treatment Key: {treatment_key}")

            except Exception as task_error:
                logging.error(f"Error processing row {index + 1} (Treatment Key {treatment_key}): {task_error}")

        # Query for comparison check
        logging.info("Checking for treatments that need comparison...")
        comparison_query = """
        WITH NumberedRows AS (
            SELECT 
                Treatment_Key,
                Treatment_Data,
                entry.[key],
                entry.[value]
            FROM Revised_MasterTable rm
            CROSS APPLY OPENJSON(Treatment_Data) entry
            WHERE ISJSON(Treatment_Data) = 1
            AND (SELECT COUNT(*) FROM OPENJSON(rm.Treatment_Data)) > 1
        ),
        LastEntry AS (
            SELECT 
                nr1.Treatment_Key,
                nr1.Treatment_Data,
                nr1.[value] as last_entry
            FROM NumberedRows nr1
            WHERE nr1.[key] = (
                SELECT MAX(nr2.[key])
                FROM NumberedRows nr2
                WHERE nr2.Treatment_Key = nr1.Treatment_Key
            )
        )
        SELECT 
            Treatment_Key,
            Treatment_Data
        FROM LastEntry le
        WHERE 
            le.last_entry IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM OPENJSON(le.last_entry) fields
                WHERE fields.[key] = 'App_Notification'
            );
        """
        
        cursor.execute(comparison_query)
        missed_rows = cursor.fetchall()
        logging.info(f"Found {len(missed_rows)} treatments needing comparison check")

        for row in missed_rows:
            try:
                treatment_key = row[0]
                treatment_data = json.loads(row[1])
                enqueue_for_comparison({
                    "treatment_key": treatment_key,
                    "treatment_data": treatment_data
                })
                logging.info(f"Queued missed comparison for Treatment Key: {treatment_key}")
            except Exception as e:
                logging.error(f"Error queueing comparison for {treatment_key}: {e}")

        logging.info("All tasks queued successfully.")
        return func.HttpResponse("Tasks queued successfully.", status_code=200)

    except Exception as e:
        logging.error(f"Error in Translation Queuing Trigger: {e}")
        alert_phone_number = "9144334333"
        alert_message = f"Alert: '{e}'"
        send_sms(alert_phone_number, alert_message)
        return func.HttpResponse(f"Error: {e}", status_code=500)

    finally:
        logging.info('Closing database connection...')
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
        logging.info('Database connection closed.')


def standardize_date(date_str):
    """Convert any date format to YYYYMMDD"""
    # Remove any hyphens from the date
    return date_str.replace('-', '')


def parse_current_phase(phase_json_str):
    """
    Attempt to parse the JSON string for the 'Phase' field.
    We handle multilingual data, e.g. [ {"en": "Phase 2"} ] or [ {"fr": "Phase 2"} ].
    Returns a string like 'Phase 2' or 'Unknown Phase' if we can’t parse anything else.
    """
    try:
        data = json.loads(phase_json_str)
        # data should be a list of dictionaries, e.g. [ { "en": "Phase 3" }, { ... } ]
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            first_dict = data[0]
            # Try an English fallback, or whichever language key is first
            if "en" in first_dict:
                return first_dict["en"]
            else:
                # fallback: the first available language’s text
                return next(iter(first_dict.values()))
        else:
            return "Unknown Phase"
    except:
        return "Unknown Phase"


@app.function_name(name="ProcessArtificialInsertionTask")
@app.queue_trigger(
    arg_name="msg",
    queue_name="artificial-insertion-tasks",
    connection="AzureWebJobsStorage"
)
async def process_artificial_insertion_task(msg: func.QueueMessage) -> None:
    logging.info("Starting artificial insertion task...")

    conn = None
    cursor = None

    def extract_multilingual_value(json_str, field_name):
        """Helper function to extract value from a multilingual JSON string."""
        try:
            data = json.loads(json_str)
            if isinstance(data, list) and len(data) > 0:
                if "en" in data[0]:
                    return data[0]["en"]
                return next(iter(data[0].values()))
            return f"Unknown {field_name}"
        except:
            return f"Unknown {field_name}"

    def decrement_counter():
        """Safely decrement the ArtificialInsertionTaskTracker."""
        try:
            cursor.execute("""
                UPDATE ArtificialInsertionTaskTracker
                SET RemainingTasks = RemainingTasks - 1
                WHERE DateKey = ?
            """, (date_key,))
            conn.commit()

            cursor.execute(
                "SELECT RemainingTasks FROM ArtificialInsertionTaskTracker WHERE DateKey = ?",
                (date_key,)
            )
            row = cursor.fetchone()
            if row:
                remaining = row[0]
                logging.info(f"Tasks remaining after decrement: {remaining}")
                if remaining == 0:
                    logging.info("All artificial insertion tasks done; calling translation now.")
                    translation_queuing_trigger()
        except Exception as e:
            logging.error(f"Failed to decrement counter: {e}")

    try:
        # 1) Parse the queue message
        body = msg.get_body().decode("utf-8")
        decoded = json.loads(body)

        treatment_key = decoded.get("treatment_key")
        date_key = decoded.get("date_key")

        if not treatment_key or not date_key:
            logging.error("Message missing treatment_key or date_key.")
            return

        logging.info("Processing artificial insertion for %s (DateKey=%s)", treatment_key, date_key)

        # 2) Connect to DB so we can decrement on errors
        conn_str = (
            f"DRIVER={driver};SERVER={server};PORT=1433;"
            f"DATABASE={database};UID={username};PWD={password}"
        )
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        # 3) Fetch existing data from Revised_MasterTable
        cursor.execute("SELECT Treatment_Data FROM Revised_MasterTable WHERE Treatment_Key = ?", (treatment_key,))
        row = cursor.fetchone()
        if not row:
            logging.error("No data found for %s in Revised_MasterTable.", treatment_key)
            decrement_counter()
            return

        treatment_data_raw = row[0]
        if not treatment_data_raw:
            logging.warning("Empty Treatment_Data for %s.", treatment_key)
            decrement_counter()
            return

        # 4) Confirm it is first-time (only 1 record)
        try:
            treatment_data = json.loads(treatment_data_raw)
        except json.JSONDecodeError as e:
            logging.error("Malformed JSON for %s: %s", treatment_key, e)
            decrement_counter()
            return

        if not isinstance(treatment_data, list):
            logging.warning("treatment_data is not a list for %s. Aborting insertion.", treatment_key)
            decrement_counter()
            return

        if len(treatment_data) > 1:
            logging.info("%s has more than 1 record; not first-time. Skipping insertion.", treatment_key)
            decrement_counter()
            return

        # Single record => "final" record
        original_record = treatment_data[0]  # e.g. { "20250109": { ... } }
        record_date_key, record_details = list(original_record.items())[0]
        original_phase = record_details.get("Phase", '[{"en":"Unknown Phase"}]')
        logging.info("Final date key: %s, original phase: %s", record_date_key, original_phase)

        parsed_phase = parse_current_phase(original_phase)  # or custom logic
        logging.info("Phase parsed as: %s", parsed_phase)

        no_earlier_phases = {"Preclinical", "Pre-Clinical", "Pre-clinical", "Discovery/Preclinical", "Unknown",
        "Discovery", "Research", "Null", "Unknown Phase", "null", "Pre-clinical/Discovery", "Early Stage Development", "", "N/A"}

        if parsed_phase in no_earlier_phases:
            logging.info(f"Skipping LLM call for {treatment_key} because current phase = {parsed_phase}.")
            decrement_counter()
            return

        # Normalize the final record's date
        final_date_str = standardize_date(record_date_key)  # e.g. "20250109"
        final_date_int = int(final_date_str) if final_date_str.isdigit() else 99999999

        # 4A) Extract core details for LLM prompt
        company_name = record_details.get("Company_Name", "Unknown Company")
        treatment_name = extract_multilingual_value(
            record_details.get("Treatment_Name", '[{"en":"Unknown Treatment"}]'),
            "Treatment"
        )
        therapeutic_area = extract_multilingual_value(
            record_details.get("Therapeutic_Area", '[{"en":"Unknown TA"}]'),
            "TA"
        )

        indication = extract_multilingual_value(
            record_details.get("Indication", '[{"en":"Unknown Indication"}]'),
            "Indication"
        )

        parsed_phase = parse_current_phase(original_phase)
        if not parsed_phase or parsed_phase == "Unknown Phase":
            current_phase_str = "Unknown Phase"
        else:
            current_phase_str = parsed_phase

        logging.info("Prompt will see current_phase_str=%s", current_phase_str)

        # 4B) Build the prompt
        prompt = f"""
        We have a newly scraped record with the following details:

        Company: {company_name}
        Treatment: {treatment_name}
        Indication: {indication}
        Therapeutic Area: {therapeutic_area}
        Current Phase: {current_phase_str}
        Current date: {datetime.now(timezone.utc).strftime('%Y%m%d')}

        Instructions:
        1. Identify all pipeline phases that come before the "Current Phase."
           - If currentPhase is "Phase 3," list "Phase 2," "Phase 1," and "Preclinical."
           - If currentPhase is "Filing" or "Submission," list "Phase 3," "Phase 2," "Phase 1," and "Preclinical."
           - If currentPhase is "Proof of Concept" list "Phase 1," and "Preclinical."
           - If currentPhase is "Phase 1," list only "Preclinical."
           - If currentPhase is "Approved," or "Registered," or "Enregistrement," list "Phase 3," "Phase 2," "Phase 1," and "Preclinical."
           - If currentPhase rule is not established above, make your best guess based on what the phase is.

        DO NOT INCLUDE THE CURRENT PHASE IN YOUR LIST.

        2. For each of those earlier phases, consult publicly available sources to find the historical date
           in YYYYMMDD format when the treatment entered that phase, in ascending order (oldest first).
           If you do not have an official date for a phase, provide your best possible guess in YYYYMMDD format.

        Output only the resulting JSON array of objects in the format:
        [
          {{
            "iso_date": "YYYYMMDD",
            "phase": "Phase 2"
          }},
          {{
            "iso_date": "YYYYMMDD",
            "phase": "Phase 3"
          }}
        ]
        No extra text, no code blocks, no explanations—only the JSON array.
        """

        # 4C) Call the LLM
        llm = ChatOpenAI(
            model="o1-mini",
            openai_api_key=openai_api_key,
            temperature=1
        )
        response = llm.invoke(prompt)
        response_text = response.content.strip()
        logging.info("LLM raw response: %s", response_text)

        # Clean up any triple backticks
        response_text = response_text.replace("```json", "").replace("```", "").strip()

        # Attempt to parse
        try:
            older_phases = json.loads(response_text)
            if not isinstance(older_phases, list):
                older_phases = []
        except json.JSONDecodeError:
            logging.warning("LLM did not return valid JSON. Using empty older_phases.")
            older_phases = []

        logging.info("older_phases: %s", older_phases)

        # 5) Insert the older phases
        for phase_obj in older_phases:
            new_phase = phase_obj.get("phase", "").strip()
            new_date = phase_obj.get("iso_date", "").strip()
            if not new_phase or not new_date:
                logging.warning("Skipping incomplete older phase info: %s", phase_obj)
                continue

            # Compare to final phase
            if new_phase.lower() == current_phase_str.lower().strip():
                logging.info("Skipping older phase that is the same as final: %s", new_phase)
                continue

            # Standardize the new date
            new_date_str = standardize_date(new_date)  # e.g. "20230101"
            if not new_date_str.isdigit():
                logging.warning("Skipping invalid iso_date from LLM: %s", new_date)
                continue

            new_date_int = int(new_date_str)

            # Enforce strictly older
            if new_date_int >= final_date_int:
                logging.info("Skipping iso_date=%s >= final date=%s for %s", new_date, record_date_key, treatment_key)
                continue

            if new_date == record_date_key:
                logging.info("Skipping iso_date=%s == final record date=%s", new_date, record_date_key)
                continue

            # Make a deep copy of the final record but override only the Phase & SourceID
            older_details = copy.deepcopy(record_details)
            older_details["Phase"] = json.dumps([{"en": new_phase}])
            source_id = datetime.now(timezone.utc).isoformat()
            older_details["SourceID"] = source_id

            # Ensure Sources table & insert new row
            cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Sources')
            BEGIN
                CREATE TABLE Sources (
                    SourceID NVARCHAR(100) PRIMARY KEY,
                    SourceName NVARCHAR(200),
                    SourceLink NVARCHAR(500),
                    Notes NVARCHAR(MAX),
                    Human_Verified NVARCHAR(MAX)
                )
            END
            """)
            insert_query = """
                INSERT INTO Sources (SourceID, SourceName, SourceLink, Notes, Human_Verified)
                VALUES (?, ?, ?, ?, ?)
            """
            cursor.execute(
                insert_query,
                (source_id, "OpenAI API", "N/A", "Artificial insertion for older phases", "No")
            )

            # Insert it into treatment_data
            artificial_record = {new_date: older_details}
            treatment_data.append(artificial_record)
            logging.info("Added older-phase record: date=%s, phase=%s for %s", new_date, new_phase, treatment_key)

        # 6) Sort + restore the final record’s original phase
        treatment_data = sort_treatment_data_by_key(treatment_data)

        for entry in treatment_data:
            dt_key, dt_details = list(entry.items())[0]
            # Compare standardized if needed
            if standardize_date(dt_key) == final_date_str:
                dt_details["Phase"] = original_phase

        # 7) Save changes to the DB
        updated_json = json.dumps(treatment_data, ensure_ascii=False)
        cursor.execute(
            "UPDATE Revised_MasterTable SET Treatment_Data = ? WHERE Treatment_Key = ?",
            (updated_json, treatment_key)
        )
        conn.commit()
        logging.info("Artificial insertion completed for %s", treatment_key)

        # 8) Decrement the insertion counter
        decrement_counter()

    except Exception as e:
        logging.error("Error in process_artificial_insertion_task: %s", e)
        # Decrement even on error
        if cursor:
            decrement_counter()

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logging.info("Finished process_artificial_insertion_task.")


def sort_treatment_data_by_key(treatment_data):
    """
    treatment_data is a list of dicts like:
      [ {"20230101": {...}}, {"20250101": {...}}, ... ]
    This sorts them ascending by date key string.
    """
    def get_date_key(entry):
        return list(entry.keys())[0]  # e.g., "20230101"

    return sorted(treatment_data, key=get_date_key)


def generate_unique_source_id():
    # Could be a timestamp or a UUID. For example:
    return datetime.now(timezone.utc).isoformat()


@app.function_name(name="ProcessTranslationTask")
@app.queue_trigger(
    arg_name="msg",
    queue_name="translation-tasks",
    connection="AzureWebJobsStorage"
)
def process_translation_task(msg: func.QueueMessage):
    logging.info('Processing translation task...')

    # Parse the queue message
    try:
        # Decode the message
        message_body = msg.get_body().decode('utf-8')
        logging.info(f"Raw message body: {message_body}")

        # Decode the base64 message
        decoded_body = json.loads(message_body)
        treatment_key = decoded_body.get("treatment_key")
        treatment_data = decoded_body.get("treatment_data")

        if not treatment_key or not treatment_data:
            logging.error("Message missing required fields.")
            return

        logging.info(f"Processing treatment key: {treatment_key}")

    except Exception as e:
        logging.error(f"Failed to parse message: {e}")
        return

    # Database connection
    conn = None
    cursor = None
    try:
        # Connect to database
        connection_string = f'DRIVER={driver};SERVER=tcp:{server};PORT=1433;DATABASE={database};UID={username};PWD={password}'
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        # Process translation
        logging.info(f"Calling translation function for treatment key: {treatment_key}")
        process_and_translate_all_entries(treatment_data, cursor, treatment_key)

        # Commit changes
        conn.commit()
        logging.info(f"Translation processing completed for {treatment_key}")

        enqueue_for_comparison({
            "treatment_key": treatment_key,
            "treatment_data": treatment_data
        })

    except Exception as e:
        logging.error(f"Error during translation processing: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def enqueue_for_comparison(task_data):
    QUEUE_NAME = "comparison-tasks"

    try:
        # Input validation
        if not task_data.get('treatment_key') or not task_data.get('treatment_data'):
            logging.error("Missing required fields in task_data")
            return

        treatment_data = task_data['treatment_data']
        if not isinstance(treatment_data, list) or len(treatment_data) < 2:
            logging.error(f"Invalid treatment_data structure for {task_data['treatment_key']}")
            return

        # Connect to Azure Queue
        queue_client = QueueClient.from_connection_string(CONNECTION_STRING, QUEUE_NAME)

        # Encode message in Base64 with manual padding
        message_json = json.dumps(task_data)
        encoded_message = base64.b64encode(message_json.encode('utf-8')).decode('utf-8')

        # Ensure proper padding
        encoded_message = encoded_message + "=" * ((4 - len(encoded_message) % 4) % 4)

        # Send the padded message
        queue_client.send_message(encoded_message)
        logging.info(f"Queued comparison task for Treatment Key: {task_data['treatment_key']}")

        # Log the queue depth
        try:
            properties = queue_client.get_queue_properties()
            message_count = properties.approximate_message_count
            logging.info(f"Current queue depth: {message_count} messages")
        except Exception as e:
            logging.warning(f"Could not get queue depth: {e}")

    except Exception as e:
        logging.error(f"Failed to add message to queue: {e} for treatment: {task_data.get('treatment_key', 'Unknown')}")
        alert_phone_number = "9144334333"
        alert_message = f"Alert: '{e}'"
        send_sms(alert_phone_number, alert_message)


@app.function_name(name="ProcessComparisonTask")
@app.queue_trigger(
    arg_name="msg",
    queue_name="comparison-tasks",
    connection="AzureWebJobsStorage"
)
async def process_comparison_task(msg: func.QueueMessage) -> None:
    NEW_QUEUE_NAME = "langchain-processing-tasks"
    logging.info('Starting process_comparison_task...')

    conn = None
    cursor = None

    try:
        # 1) Parse incoming message
        task_data = json.loads(msg.get_body().decode('utf-8'))
        logging.info(f"Parsed message: {task_data}")

        # Extract relevant fields
        treatment_key = task_data.get("treatment_key")
        treatment_data = task_data.get("treatment_data")

        if not treatment_key or not treatment_data:
            logging.error(f"Missing fields: treatment_key={treatment_key}, treatment_data={treatment_data}")
            return  # Exit early

        # 2) Ensure we have at least two data points
        if len(treatment_data) < 2:
            logging.info("Insufficient data for comparison; need at least 2 records.")
            return

        # 3) Identify previous vs latest records
        previous_record = treatment_data[-2]
        latest_record   = treatment_data[-1]

        previous_details = list(previous_record.values())[0]
        latest_details   = list(latest_record.values())[0]

        conn_str = f"DRIVER={driver};SERVER={server};PORT=1433;DATABASE={database};UID={username};PWD={password}"
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        # 4) Check for changes
        if not has_changes(previous_details, latest_details, treatment_key):
            logging.info("No changes detected between previous and latest.")

            # ------------------------------------------
            # Use MultilingualData for 'App_Notification'
            # ------------------------------------------
            # Build a notification message in a MultilingualData object
            notif_data = MultilingualData()
            # The "value" can be any structure (dict, string, etc.), as long
            # as you stay consistent with your usage. Here we store a dict
            # with priority, description, info_types in English.
            notif_data.add_translation("en", {
                "priority": 1,
                "description": "No changes detected.",
                "info_types": []
            })

            notif_collection = MultilingualDataCollection()
            notif_collection.add_data(notif_data)


            # If you need other languages, just add them, e.g.:
            # notif_data.add_translation("fr", {
            #     "priorité": 1,
            #     "description": "Aucun changement détecté.",
            #     "info_types": []
            # })

            # Then store the entire object as JSON in an array
            # so it matches your existing structure: [ { "en": {...} } ]
            latest_details["App_Notification"] = notif_collection.get_collection_as_json()

            # 4a) Update the DB with the revised treatment_data
            try:
                updated_json = json.dumps(treatment_data, ensure_ascii=False)
                update_query = """UPDATE Revised_MasterTable
                                  SET Treatment_Data = ?
                                  WHERE Treatment_Key = ?"""
                cursor.execute(update_query, (updated_json, treatment_key))
                conn.commit()
                logging.info(f"Set 'No changes detected' App_Notification for {treatment_key}")
            except Exception as e:
                logging.error(f"Error updating DB with no-changes notification: {e}")
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

            return  # End here—no need to call LangChain

        # If changes exist:
        logging.info("Changes detected. Proceeding with LangChain queue...")

        # 5) Queue for LangChain processing
        queue_client = QueueClient.from_connection_string(CONNECTION_STRING, NEW_QUEUE_NAME)
        encoded_message = base64.b64encode(json.dumps(task_data).encode('utf-8')).decode('utf-8')
        queue_client.send_message(encoded_message)

        logging.info(f"Task queued for LangChain processing. Treatment Key: {treatment_key}")

    except Exception as e:
        logging.error(f"Error during comparison task: {e}")
    finally:
        logging.info('process_comparison_task completed.')


@app.function_name(name="LangChainProcessingWorker")
@app.queue_trigger(
    arg_name="msg",
    queue_name="langchain-processing-tasks",
    connection="AzureWebJobsStorage"
)
async def langchain_processing_worker(msg: func.QueueMessage):
    logging.info('Starting langchain_processing_worker...')

    try:
        # Parse incoming message
        task_data = json.loads(msg.get_body().decode('utf-8'))
        logging.info(f"Parsed task data: {task_data}")

        treatment_key = task_data.get("treatment_key")
        treatment_data = task_data.get("treatment_data")

        # Basic validation
        if not treatment_key or not treatment_data:
            logging.error("Missing 'treatment_key' or 'treatment_data'.")
            return

        if len(treatment_data) < 2:
            logging.error(f"Insufficient data for comparison. Key: {treatment_key}")
            return

        # Get all consecutive pairs of entries for comparison
        entries_to_process = []
        for i in range(len(treatment_data) - 1):
            current_record = treatment_data[i]
            next_record = treatment_data[i + 1]
            
            # Skip if next entry already has a notification
            next_details = list(next_record.values())[0]
            if not next_details.get("App_Notification"):
                entries_to_process.append((current_record, next_record))

        if not entries_to_process:
            logging.info("No entries need processing")
            return

        # Set up LLM once
        llm = ChatOpenAI(
            model="o1-mini",
            openai_api_key=openai_api_key,
            temperature=1
        )

        prompt_template = PromptTemplate(
            input_variables=["key", "old_data", "new_data"],
            template="""Compare the following treatment details.

            Treatment Key: {key}
            Old Data: {old_data}
            New Data: {new_data}

            Ignore changes in the following fields:
            - Date_Scraped
            - App_Notification
            - Translations

            Provide:
            1. Priority of change (1 to 5). Do Not Use 0. 1 is least important. 5 is most important.
            2. Description of the change. Please mention the name of the treatment and the company it is associated with in the description.
            3. Info Types based on the following categories: ["Pipeline Info", "Financial Info", "Personnel Info", "MAndA", "Layoffs", "New Hires", "Therapy Approval", "Indication Change", "Earnings Report"].

            Return only a JSON object with this exact structure (no extra text or explanation):
            {{
                "priority": <number between 1 and 5>,
                "description": "<clear description of changes>",
                "info_types": ["<category>"]
            }}"""
        )

        # Connect to DB once
        connection_string = f"DRIVER={driver};SERVER={server};PORT=1433;DATABASE={database};UID={username};PWD={password}"
        with pyodbc.connect(connection_string) as conn:
            with conn.cursor() as cursor:
                # Process all pairs
                for previous_record, latest_record in entries_to_process:
                    previous_details = list(previous_record.values())[0]
                    latest_details = list(latest_record.values())[0]
                    latest_date = list(latest_record.keys())[0]

                    # Filter out ignored fields
                    def filter_ignored_fields(details):
                        ignored_fields = ["Date_Scraped", "App_Notification", "Translations", "SourceID"]
                        return {k: v for k, v in details.items() if k not in ignored_fields}

                    filtered_old_data = filter_ignored_fields(previous_details)
                    filtered_new_data = filter_ignored_fields(latest_details)

                    # Build and send prompt
                    prompt = prompt_template.format(
                        key=treatment_key,
                        old_data=json.dumps(filtered_old_data, indent=2),
                        new_data=json.dumps(filtered_new_data, indent=2)
                    )
                    logging.info(f"Sending prompt to LangChain LLM for date {latest_date}...")

                    try:
                        response = llm.invoke(prompt)
                        response_text = response.content.replace("```json", "").replace("```", "").strip()
                        result_json = json.loads(response_text)
                        logging.info(f"Parsed JSON from LLM for date {latest_date}: {result_json}")

                        # Insert into stream table
                        insert_stream_data(conn, result_json, previous_details, latest_details)
                        logging.info(f"Stream data inserted for {treatment_key} date {latest_date}")

                        # Create notification
                        notif_data = MultilingualData()
                        notif_data.add_translation("en", result_json)
                        notif_collection = MultilingualDataCollection()
                        notif_collection.add_data(notif_data)
                        notification_json = notif_collection.get_collection_as_json()

                        # Update the notification in treatment_data
                        for entry in treatment_data:
                            if list(entry.keys())[0] == latest_date:
                                list(entry.values())[0]["App_Notification"] = notification_json
                                logging.info(f"Added notification to entry with date {latest_date}")
                                break

                    except Exception as e:
                        logging.error(f"Error processing entry for date {latest_date}: {e}")
                        continue

                # Single database update at the end with all notifications
                cursor.execute(
                    "UPDATE Revised_MasterTable SET Treatment_Data = ? WHERE Treatment_Key = ?",
                    (json.dumps(treatment_data, ensure_ascii=False), treatment_key)
                )
                conn.commit()
                logging.info(f"Updated database with all notifications for {treatment_key}")

    except Exception as e:
        logging.error(f"Error during LangChain processing: {e}")
    finally:
        logging.info('LangChain processing task completed.')
        
def create_stream_table(conn):
    cursor = conn.cursor()

    # Check if the table exists
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Stream')
        BEGIN
            CREATE TABLE Stream (
                id INT PRIMARY KEY IDENTITY(1,1),
                priority INT,
                description NVARCHAR(255),
                timestamp DATETIME,
                raw_response NVARCHAR(MAX),
                old_object NVARCHAR(MAX),
                new_object NVARCHAR(MAX)
            )
        END
    """)
    conn.commit()

    # Fetch company names from Profile_Table
    cursor.execute("SELECT DISTINCT Company_Name FROM Profile_Table")
    companies = [row.Company_Name for row in cursor.fetchall()]

    # Fetch category names from Categories table
    cursor.execute("SELECT DISTINCT category FROM Categories")
    categories = [row.category for row in cursor.fetchall()]

    info_types = ["Pipeline Info", "Financial Info", "Personnel Info", "MAndA", "Layoffs", "New Hires", "Therapy Approval", "Indication Change", "Earnings Report"]

    # Add company columns dynamically if they don't exist
    for company in companies:
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE Name = N'{company}' AND Object_ID = Object_ID(N'Stream'))
            BEGIN
                ALTER TABLE Stream ADD [{company}] BIT
            END
        """)

    # Add category columns dynamically if they don't exist
    for category in categories:
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE Name = N'{category}' AND Object_ID = Object_ID(N'Stream'))
            BEGIN
                ALTER TABLE Stream ADD [{category}] BIT
            END
        """)

    # Add info type columns dynamically if they don't exist
    for info_type in info_types:
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE Name = N'{info_type}' AND Object_ID = Object_ID(N'Stream'))
            BEGIN
                ALTER TABLE Stream ADD [{info_type}] BIT
            END
        """)

    conn.commit()
    cursor.close()

def insert_stream_data(conn, response, old_object, new_object):
    cursor = conn.cursor()

    try:
        # Ensure `response` is a dict; if it's JSON, parse it
        if isinstance(response, dict):
            data = response
        else:
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                logging.error(f"Failed to parse JSON response: {response}")
                # Insert only raw_response, old_object, new_object
                insert_query = """
                    INSERT INTO Stream (raw_response, old_object, new_object)
                    OUTPUT inserted.id
                    VALUES (?, ?, ?)
                """
                cursor.execute(insert_query, (response, json.dumps(old_object), json.dumps(new_object)))
                new_id = cursor.fetchone()[0]
                conn.commit()
                
                # If you still want to do matching here, you can call 
                # match_clients_with_notification(conn, new_id), but presumably 
                # you won't have the normal columns set. Then return early.
                return

        # -------------------------
        # EXTRACT FIELDS FROM data
        # -------------------------
        priority = data.get("priority", 1)  # default=1
        description = data.get("description", "No changes detected")
        timestamp = data.get("timestamp", datetime.utcnow())  # default to current UTC
        info_types = data.get("info_types", [])

        # Keep a raw_response string for the original data
        raw_response = response if isinstance(response, str) else json.dumps(response)

        # -------------------------
        # FETCH COMPANIES, CATEGORIES, ETC. AS BEFORE
        # -------------------------
        cursor.execute("SELECT DISTINCT Company_Name FROM Profile_Table")
        companies = [row.Company_Name for row in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT category FROM Categories")
        categories = [row.category for row in cursor.fetchall()]

        all_info_types = [
            "Pipeline Info", "Financial Info", "Personnel Info", "MAndA",
            "Layoffs", "New Hires", "Therapy Approval", "Indication Change", "Earnings Report"
        ]

        companies_categories_info_types = companies + categories + all_info_types

        columns_and_values = {}

        # For each field in the big combined list, set True if it's in info_types
        for field in companies_categories_info_types:
            field_formatted = f"[{field}]"
            columns_and_values[field_formatted] = (field in info_types)

        # Old/new company names
        old_company_name = old_object.get("Company_Name", "")
        new_company_name = new_object.get("Company_Name", "")

        # If the old or new company name exists in Profile_Table, set that column to True
        for c_name in [old_company_name, new_company_name]:
            if c_name and c_name in companies:
                columns_and_values[f"[{c_name}]"] = True

                # Check categories for this company
                cursor.execute("SELECT Categories FROM Profile_Table WHERE Company_Name = ?", (c_name,))
                cat_result = cursor.fetchone()
                if cat_result:
                    try:
                        categories_list = json.loads(cat_result.Categories)
                        for cat in categories_list:
                            cat_col = f"[{cat}]"
                            if cat_col in columns_and_values:
                                columns_and_values[cat_col] = True
                    except json.JSONDecodeError:
                        pass  # If the categories are not valid JSON, ignore

        # These final columns store metadata
        columns_and_values["old_object"] = json.dumps(old_object)
        columns_and_values["new_object"] = json.dumps(new_object)
        columns_and_values["raw_response"] = raw_response
        columns_and_values["timestamp"] = timestamp

        # Build the final insert
        columns = ", ".join(columns_and_values.keys()) + ", priority, description"
        placeholders = ", ".join("?" for _ in columns_and_values) + ", ?, ?"
        values = list(columns_and_values.values()) + [priority, description]

        insert_query = f"""
            INSERT INTO Stream ({columns})
            OUTPUT inserted.id
            VALUES ({placeholders})
        """

        # Insert and get new Stream row ID
        cursor.execute(insert_query, values)
        new_id = cursor.fetchone()[0]
        conn.commit()

        # -----------------------------------------------
        # CALL match_clients_with_notification WITH `new_id`
        # -----------------------------------------------
        logging.info(f"Successfully inserted new Stream row with id={new_id}. Now matching clients...")
        matched_clients = match_clients_with_notification(conn, new_id)

        # Optionally build a user-friendly description/title
        description_title = f"{new_company_name} Notification: {description}"

        # Send notifications to matched clients
        for client in matched_clients:
            logging.info(f"Sending notification to client: {client}")
            if client.get("Email"):
                send_email(client["Email"], "New Notification", description_title)
            if client.get("text"):
                send_sms(client["text"], description_title)
            if client.get("Call"):
                send_call(client["Phone"], description_title)

    except json.JSONDecodeError:
        logging.error(f"JSON parsing failed for response: {response}")
        insert_query = """
            INSERT INTO Stream (raw_response, old_object, new_object)
            OUTPUT inserted.id
            VALUES (?, ?, ?)
        """
        cursor.execute(insert_query, (response, json.dumps(old_object), json.dumps(new_object)))
        new_id = cursor.fetchone()[0]
        conn.commit()

        # If desired, call match_clients_with_notification here too.
    except pyodbc.Error as e:
        logging.error(f"Failed to insert stream data: {e}")
        conn.rollback()
    finally:
        cursor.close()


# Next Step!!!!!!

def match_clients_with_notification(conn, stream_id):
    """
    1. Fetch the newly inserted row from Stream by its ID.
    2. Collect all columns that are set to 1 (true) except for known fields like raw_response, old_object, new_object, etc.
    3. Compare each client in Notification_Request_Object_Table to see if they have the same columns set to true.
    4. If client priority is <= stream priority, add them to matched_clients.
    5. Return the matched_clients so you can send notifications.
    """

    logging.info(">>> Entering match_clients_with_notification with stream_id=%s", stream_id)

    cursor = conn.cursor()

    # ----------------------------------------------------
    # STEP 1: Fetch the Stream row that was just inserted
    # ----------------------------------------------------
    logging.info("Retrieving Stream row for ID=%s...", stream_id)
    cursor.execute("SELECT * FROM Stream WHERE id = ?", (stream_id,))
    row = cursor.fetchone()
    if not row:
        logging.warning("No Stream row found for id=%s", stream_id)
        cursor.close()
        return []

    columns = [desc[0] for desc in cursor.description]
    row_dict = dict(zip(columns, row))

    logging.info("Stream row retrieved: %s", row_dict)

    # Priority & Description from the stream
    stream_priority = row_dict.get("priority", 1)
    stream_description = row_dict.get("description", "No description")

    # Known fields we want to ignore (these are not "company" or "info type" columns)
    ignored_fields = {
        "id", "raw_response", "old_object", "new_object", "timestamp",
        "priority", "description"  # we already extracted these
    }

    # ----------------------------------------------------
    # STEP 2: Collect columns in Stream row that are TRUE
    # ----------------------------------------------------
    relevant_companies = []
    for col_name, col_value in row_dict.items():
        # Check if this column is not in the ignored set and has a truthy value
        # e.g. 1, True, etc.
        if col_name not in ignored_fields:
            if col_value == 1 or col_value is True:
                relevant_companies.append(col_name)  # e.g. [Zydus Pharmaceuticals]

    logging.info("Relevant columns set to True in stream row: %s", relevant_companies)

    # ----------------------------------------------------
    # STEP 3: Fetch all clients from Notification_Request_Object_Table
    # ----------------------------------------------------
    logging.info("Fetching clients from Notification_Request_Object_Table...")
    cursor.execute("SELECT * FROM Notification_Request_Object_Table")
    nrot_columns = [desc[0] for desc in cursor.description]
    clients = [dict(zip(nrot_columns, r)) for r in cursor.fetchall()]

    logging.info("Found %d clients in Notification_Request_Object_Table.", len(clients))

    # ----------------------------------------------------
    # STEP 4: Determine matched clients
    # ----------------------------------------------------
    matched_clients = []

    for i, client in enumerate(clients):
        logging.info("Evaluating client #%d: %s", i+1, client)

        client_priority = client.get("Priority", 1)  # or 'priority' if your column is named that

        # Check if this client has at least one of the relevant companies set to True
        # (and meets the priority condition)
        # For example, does the client also have [Zydus Pharmaceuticals] = 1?
        # We'll use `any(...)` to check if at least one matches.
        has_company_match = any(
            client.get(company) in (1, True) 
            for company in relevant_companies
        )

        logging.info(
            "Client #%d => has_company_match=%s, stream_priority=%s, client_priority=%s",
            i+1, has_company_match, stream_priority, client_priority
        )

        if has_company_match and (stream_priority >= client_priority):
            # Or > client_priority if you want strictly higher
            logging.info("Client #%d matched!", i+1)
            matched_clients.append(client)
        else:
            logging.info("Client #%d did not match.", i+1)

    cursor.close()

    logging.info("Number of matched clients: %d", len(matched_clients))
    logging.info("Matched clients: %s", matched_clients)
    logging.info("<<< Exiting match_clients_with_notification...\n")

    return matched_clients


def send_email(email_address, subject, message):
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login("your_email@gmail.com", "your_password")
            server.sendmail("your_email@gmail.com", email_address, f"Subject: {subject}\n\n{message}")
        print(f"Email sent to {email_address}")
    except Exception as e:
        print(f"Failed to send email to {email_address}: {e}")

def send_sms(phone_number, message):
    try:
        client_code_one = os.getenv("CLIENT_CODE_ONE")
        client_code_two = os.getenv("CLIENT_CODE_TWO")
        client = Client(client_code_one, client_code_two)

        from_number = os.getenv("TWILIO_PHONE_NUMBER")
        client.messages.create(body=message, from_=from_number, to=phone_number)
        print(f"SMS sent to {phone_number}")
    except Exception as e:
        print(f"Failed to send SMS to {phone_number}: {e}")

def send_call(phone_number, message):
    try:
        client = Client("account_sid", "auth_token")
        call = client.calls.create(twiml=f'<Response><Say>{message}</Say></Response>', to=phone_number, from_="+123456789")
        print(f"Call made to {phone_number}")
    except Exception as e:
        print(f"Failed to make call to {phone_number}: {e}")

def has_changes(old_details, new_details, treatment_key):
    """
    Returns True if there's any difference in non-ignored fields, 
    and inserts debug rows into ChangeDebugLog for each difference.
    """
    # Fields we ignore when checking for changes
    ignore_keys = ['Date_Scraped', 'App_Notification', 'Company_Name', "SourceID"]

    changed = False

    for key in old_details.keys():
        if key not in ignore_keys:
            old_val = old_details.get(key)
            new_val = new_details.get(key)

            if old_val != new_val:
                logging.info(
                    f"[DEBUG] Detected a difference in '{treatment_key}', "
                    f"field='{key}' old='{old_val}' vs new='{new_val}'"
                )

                changed = True

    return changed
