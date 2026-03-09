# Team Roles - Harvester Agent Implementation

## Project Overview
We're building the Harvester Agent for Fivos - an AI-powered web scraper that pulls medical device specs from manufacturer websites and stores them in a data lake. This feeds into the Validator Agent which compares the data against the FDA's GUDID database.

---

## Wyatt Ladner - Web Automation Lead

### What You're Building
The core engine that actually controls the browser and visits websites.

### In Simple Terms
Think of this as the "driver" of the system. You're building the code that opens a browser (invisibly, in headless mode), goes to URLs, waits for pages to load, and handles all the annoying stuff like slow sites, timeouts, and pages that block bots.

### Key Responsibilities
- **Headless Browser Setup**: Get Playwright or Selenium working in headless mode so it can run on a server without a display
- **Page Navigation**: Write the logic that visits URLs, follows links, and handles redirects
- **Retry Logic**: If a page fails to load, retry up to 3 times with 5-second delays between attempts
- **Timeout Handling**: Set a 30-second max wait per page - if it takes longer, mark it as failed and move on
- **Rate Limiting**: Add configurable delays between requests (default 2 seconds) so we don't get blocked
- **JavaScript Rendering**: Wait for dynamic content to load before we try to extract data

### Tech You'll Use
- Python
- Playwright (preferred) or Selenium
- asyncio for handling multiple requests

### Example of What Your Code Does
```
1. Receive URL from the system
2. Open headless browser
3. Navigate to URL
4. Wait for JavaScript to render (up to 30 sec)
5. If failed -> retry up to 3 times
6. If success -> pass the page HTML to Jason's extraction code
7. Log the result either way
```

---

## Jason Sonith - Data Pipeline & Security

### What You're Building
The extraction and normalization layer that pulls structured data out of raw HTML and makes it consistent.

### In Simple Terms
Once Wyatt's code gets us to a product page, your code looks at the HTML and figures out what the actual device specs are. Then you clean up the data - converting "10 centimeters" and "100mm" to the same format, fixing inconsistent naming, etc. You also handle any security stuff like storing credentials safely.

### Key Responsibilities
- **Data Extraction Pipeline**: Take the HTML from Wyatt's browser and pull out the device specs
- **Field Normalization**: Standardize units (mm vs cm vs inches), formats (dates, numbers), and naming conventions
- **Schema Mapping**: Convert messy website data into our clean internal data structure
- **Credential Security**: If any manufacturer sites need login, handle those credentials securely (environment variables, never hardcoded)
- **Validation**: Basic checks to make sure extracted data looks reasonable before storing

### Tech You'll Use
- Python
- BeautifulSoup or lxml for HTML parsing
- Regular expressions for pattern matching
- python-dotenv for secure credential handling

### Example of What Your Code Does
```
1. Receive page HTML from Wyatt's automation code
2. Parse HTML and find the spec table/list
3. Extract fields: device name, dimensions, model number, etc.
4. Normalize: "10 cm" -> "100 mm", "ACME Corp." -> "ACME Corporation"
5. Validate: dimensions should be numbers, names shouldn't be empty
6. Pass clean structured data to Ralph's storage code
```

---

## Ryan Tucker - Site Adapters

### What You're Building
Manufacturer-specific configurations that tell the system how to navigate and extract data from each unique website.

### In Simple Terms
Every manufacturer website is different. Medtronic's site looks nothing like Abbott's. Your job is to create "adapters" - basically config files and small code modules - that describe how to find product pages and where the specs live on each site. When a site changes its layout (which happens often), you update the adapter.

### Key Responsibilities
- **Adapter Framework**: Design a system where each manufacturer has its own config file
- **CSS/XPath Selectors**: Figure out the selectors that locate specs on each site
- **Site Discovery**: For catalog mode, define how to find all product pages on a site
- **Layout Change Handling**: When sites update, update the adapters without breaking the whole system
- **Documentation**: Document each adapter so others can add new manufacturers later

### Tech You'll Use
- Python
- YAML or JSON for config files
- Browser DevTools for finding selectors
- XPath and CSS selector syntax

### Example Adapter Config
```yaml
manufacturer: medtronic
base_url: https://www.medtronic.com/products
catalog_mode:
  product_list_selector: ".product-card a"
  pagination_selector: ".next-page"
extraction:
  device_name: "h1.product-title"
  dimensions: "#specs-table tr:contains('Dimensions') td"
  model_number: ".model-number span"
```

---

## Ralph Mouawad - Data Lake & Storage

### What You're Building
The database layer where all harvested device specs get stored.

### In Simple Terms
You're setting up MongoDB (or similar NoSQL database) and designing how the data gets organized. Every device we scrape needs to be stored with all its specs plus metadata like where it came from, when we scraped it, and which harvest run it was part of. The Validator Agent will later read from this same database.

### Key Responsibilities
- **Database Setup**: Install and configure MongoDB (or chosen NoSQL solution)
- **Schema Design**: Design the document structure for harvested devices
- **Write Operations**: Build functions that Jason's code calls to save extracted data
- **Metadata Tracking**: Every record needs: source URL, timestamp, manufacturer, harvest run ID
- **Indexing**: Set up indexes so the Validator can query efficiently
- **Data Integrity**: Handle duplicates, updates to existing records, etc.

### Tech You'll Use
- MongoDB (or PostgreSQL with JSONB)
- Python with pymongo
- Docker for local database setup

### Example Document Structure
```json
{
  "_id": "ObjectId(...)",
  "harvest_run_id": "HR-10011",
  "manufacturer": "Medtronic",
  "device_name": "CardioSync Pacemaker Model X",
  "model_number": "CS-2000X",
  "dimensions": {
    "length_mm": 45,
    "width_mm": 32,
    "height_mm": 8
  },
  "source_url": "https://medtronic.com/products/cs-2000x",
  "harvested_at": "2026-01-20T14:30:00Z",
  "raw_html_ref": "s3://bucket/raw/HR-10011/page-42.html"
}
```

---

## Jonathan Gammill - Run Management & Logging

### What You're Building
The orchestration layer that kicks off harvest runs, tracks progress, and logs everything.

### In Simple Terms
You're building the "control center" for the Harvester. Your code starts harvest jobs, keeps track of how many pages we've visited, how many succeeded or failed, and writes detailed logs. The dashboard (that someone else builds) will read your logs to show the pretty progress bars and status info.

### Key Responsibilities
- **Run Orchestration**: Start/stop harvest runs, manage the queue of URLs to visit
- **Progress Tracking**: Track pages visited, devices found, specs extracted, errors
- **Harvest Run IDs**: Generate unique IDs for each run (like "HR-10011")
- **Logging System**: Comprehensive logs - what happened, when, success/failure, error details
- **Export Functionality**: Export logs as JSON for the dashboard or debugging
- **Scheduler Integration**: Eventually, ability to schedule runs (cron-style)
- **Retry Queue**: Track failed pages so they can be retried later

### Tech You'll Use
- Python
- Python logging module (or loguru for nicer logs)
- JSON for export format
- SQLite or a simple table in the main DB for run metadata

### Example Log Output
```json
{
  "run_id": "HR-10011",
  "status": "running",
  "started_at": "2026-01-20T14:00:00Z",
  "manufacturer": "Medtronic",
  "progress": {
    "pages_visited": 52,
    "pages_total": 500,
    "devices_found": 16,
    "specs_extracted": 486,
    "errors": 8
  },
  "recent_activity": [
    {"time": "14:16:05", "url": "/product/1052", "result": "success"},
    {"time": "14:16:03", "url": "/product/1051", "result": "success"}
  ]
}
```

---

## How It All Connects

```
┌─────────────────────────────────────────────────────────────────┐
│                    JONATHAN - Run Management                     │
│         (Starts runs, tracks progress, manages queue)            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     WYATT - Web Automation                       │
│         (Opens browser, visits URLs, handles retries)            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      RYAN - Site Adapters                        │
│    (Tells the system where to find specs on each website)        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                  JASON - Data Pipeline & Security                │
│        (Extracts specs from HTML, normalizes data)               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     RALPH - Data Lake Storage                    │
│       (Saves everything to MongoDB with full metadata)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Getting Started - Week 1 Priorities

| Person | First Task |
|--------|------------|
| **Wyatt** | Get Playwright working in Python, successfully load a test page |
| **Ryan** | Pick one manufacturer (Medtronic?), map out their site structure |
| **Jason** | Write a basic HTML parser that can extract a simple spec table |
| **Ralph** | Set up MongoDB locally (Docker recommended), create the base schema |
| **Jonathan** | Design the run tracking data model, basic logging setup |

**Pair Programming Suggestion**: Wyatt + Ryan should work together first to get a single manufacturer working end-to-end. Once that proof-of-concept works, the rest of the pieces integrate.

---

## Questions to Resolve as a Team

1. Which manufacturer do we start with for the MVP?
2. Playwright vs Selenium - need to decide and stick with it
3. MongoDB vs PostgreSQL - both work, pick one
4. How do we handle manufacturer sites that require login?
5. Where does this run - local machines for now, cloud later?
