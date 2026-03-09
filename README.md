# Zanalytix

A pharmaceutical treatment pipeline intelligence platform that automatically scrapes, processes, and monitors drug development data from 60+ pharmaceutical companies. It detects changes in treatment pipelines, translates data across languages, and routes intelligent notifications to stakeholders based on their preferences.

## Architecture

```
Schedule Trigger
      |
      v
HTML Scraping (Zyte API) --> 60+ Company Parsers (BeautifulSoup)
      |
      v
Data Standardization (Phase Normalization, Text Cleaning)
      |
      v
Multilingual Translation
      |
      v
Change Detection (GPT-4o via LangChain)
      |
      v
Notification Routing (Twilio SMS/Calls, Email)
```

**Runtime:** Azure Functions (Python) with queue-based task orchestration
**API Layer:** Flask with blueprints for user management, preferences, and treatment search
**Database:** Azure SQL Server
**Key Integrations:** Zyte (web scraping), OpenAI GPT-4o (change analysis), Twilio (notifications), LangChain (LLM orchestration)

## Features

- **Pipeline Scraping** - Automated scraping of 60+ pharma company pipeline pages with company-specific parsers
- **Phase Normalization** - Maps 170+ phase synonyms to canonical forms (Phase 1, Phase 2/3, Registration, Approved, etc.)
- **Multilingual Support** - Translation infrastructure for treatment data across languages
- **AI-Powered Change Detection** - GPT-4o compares old vs new treatment data, assigns priority (1-5), categorizes changes (Pipeline Info, Therapy Approval, M&A, etc.)
- **Smart Notification Routing** - Matches detected changes against user preferences for company, category, info type, and priority threshold
- **User Management** - Registration, authentication, role-based access, contact/notification preferences
- **Treatment Search** - Filter by treatment name, target, phase, indication, or company
- **Scheduling System** - Calendar-based scraping schedules with recurrence rules and auto-extension

## Azure Functions

| Function | Trigger | Purpose |
|---|---|---|
| `ScrapeHTMLTrigger` | HTTP GET `/scrape_html_trigger` | Reads scheduled tasks from Calendar table, enqueues scraping jobs |
| `CheckMissingNotificationsTrigger` | HTTP GET `/missing_notifications_check` | Finds treatments missing notifications, enqueues comparison tasks |
| `ProcessQueueTrigger` | Queue `scraping-tasks` | Fetches HTML via Zyte, runs company parser, stores in MasterTable |
| `ProcessArtificialInsertionTask` | Queue `artificial-insertion-tasks` | Cleans, standardizes, and enriches treatment data |
| `ProcessTranslationTask` | Queue `translation-tasks` | Translates treatment fields to multiple languages |
| `ProcessComparisonTask` | Queue `comparison-tasks` | GPT-4o change detection, updates Stream table |
| `LangChainProcessingWorker` | Queue `langchain-processing-tasks` | Advanced LLM-based data processing |

## Flask API (master_scheduler.py)

Blueprints:

| Blueprint | Endpoints |
|---|---|
| `login_bp` | User authentication |
| `signup_bp` | User registration |
| `forgot_password_bp` | Password recovery |
| `notifications_bp` | Trigger and manage notifications |
| `contact_preferences_bp` | Save/update contact info (email, SMS, phone, social) |
| `preferences_bp` | Notification preference management |
| `retreive_options_bp` | Retrieve user preference options |
| `scheduling_options_bp` | Scraping schedule configuration |
| `fetch_treatments_bp` | Treatment search and visualization |
| `admin_console_bp` | Admin operations |
| `scripts_bp` | Helper utilities |

## Data Model

**Revised_MasterTable** - Primary storage. Each row is a treatment keyed by `Treatment_Key`, with `Treatment_Data` containing a JSON array of dated snapshots:

```json
[
  {"20240301": {"Company_Name": "Pfizer", "Treatment_Name": "...", "Phase": "Phase 3", ...}},
  {"20240302": {"Company_Name": "Pfizer", "Treatment_Name": "...", "Phase": "Approved", ...}}
]
```

**Stream** - Change tracking. Stores GPT-4o raw responses, old/new objects, priority, description, and per-company flags.

**Notification_Request_Object_Table** - User notification preferences including company selections, info type filters, and priority thresholds.

## Company Pipelines

Each company has a dedicated module (`{company}_pipeline.py`) implementing:

- `fetch_{company}_html()` - Retrieves the pipeline page HTML
- `process_{company}_html()` - Parses HTML into structured `MasterTable` objects

Supported companies include: AbbVie, Amgen, AstraZeneca, Bayer, Biogen, BMS, Eli Lilly, GSK, Johnson & Johnson, Merck, Novartis, Novo Nordisk, Pfizer, Roche, Sanofi, Takeda, and 40+ more.

## Setup

### Prerequisites

- Python 3.x
- Azure Functions Core Tools
- ODBC Driver 17 for SQL Server
- Azure SQL Server instance
- API keys for Zyte, OpenAI, and Twilio

### Environment Variables

Create a `.env` file:

```env
# Azure SQL Server
SERVER=your-server.database.windows.net
DATABASE=your-database
USERNAME=your-username
PASSWORD=your-password
DRIVER={ODBC Driver 17 for SQL Server}

# Azure Storage (for queues)
CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;

# OpenAI
OPENAI_API_KEY=your-openai-key

# Zyte Web Scraping
ZYTE_API_KEY=your-zyte-key

# Twilio
CLIENT_CODE_ONE=your-twilio-account-sid
CLIENT_CODE_TWO=your-twilio-auth-token

# Email (SMTP)
SMTP_EMAIL=your-email@gmail.com
SMTP_PASSWORD=your-app-password
```

### Install & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run Azure Functions locally
func start

# Run Flask API
python master_scheduler.py
```

### Deploy to Azure

```bash
func azure functionapp publish <your-function-app-name>
```

## Tech Stack

| Layer | Technology |
|---|---|
| Serverless Compute | Azure Functions (Python) |
| Web Framework | Flask |
| Database | Azure SQL Server (pyodbc) |
| Task Queues | Azure Storage Queue |
| Web Scraping | Zyte API, BeautifulSoup4 |
| AI/LLM | OpenAI GPT-4o, LangChain |
| Notifications | Twilio (SMS, Voice) |
| Translation | translate (Python), OpenAI |
