# Fivos - Medical Device Data Harvesting & Validation

A multi-agent AI system that automates the process of checking medical device data between manufacturer websites and the FDA's GUDID database.

Built by **Vibe Coders** for [Fivos](https://www.fivoshealth.com) as a senior design project (CIS 497).

## The Problem

The FDA maintains a database called GUDID (Global Unique Device Identification Database) that is supposed to be the single source of truth for medical device information. In practice, the data in GUDID often does not match what manufacturers have on their own websites. Things like wrong dimensions, outdated brand names, or mismatched model numbers can cause real problems with patient records and equipment ordering.

Right now, Fivos employees have to manually check thousands of entries by hand. That is slow, tedious, and easy to mess up. This project automates most of that work.

## How It Works

The system follows a **Collect, Compare, Correct** workflow:

**The Harvester** crawls manufacturer websites using Playwright, renders JavaScript-heavy pages, and extracts device specs using a 7-model LLM fallback chain (Groq → NVIDIA NIM → Ollama local). It works on any manufacturer site without per-site configuration. Extracted records are stored in MongoDB.

**The Validator** compares harvested records against the FDA's GUDID API. It checks model numbers, catalog numbers, brand names, company names, and description similarity. Each device gets a match / partial match / mismatch verdict.

**The Review Dashboard** is a web interface where human reviewers see discrepancies side-by-side — harvested value vs GUDID value — and pick the correct one for each field. Their corrections update the database directly.

## Tech Stack

| Layer | Tools |
|---|---|
| Language | **Python 3.13.7** |
| Web Scraping | Playwright (async, headless Chromium) |
| AI / LLM | Groq + NVIDIA NIM (cloud) → Ollama (local fallback) |
| Database | MongoDB |
| Web UI | FastAPI + Jinja2 |
| HTML Parsing | BeautifulSoup4 + lxml |
| Version Control | Git / GitHub |

## Project Structure

```
├── app/                    # FastAPI web dashboard
│   ├── main.py             # App entry point
│   ├── routes/             # dashboard, harvester, validate, gudid, review, api
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS
├── harvester/
│   └── src/
│       ├── pipeline/       # Core: runner, llm_extractor, parser, emitter
│       ├── web_scraper/    # Playwright browser automation
│       ├── site_adapters/  # YAML CSS selector configs (optional override)
│       ├── normalizers/    # Text, model numbers, dates, units, booleans
│       ├── validators/     # GUDID client, comparison, record validation
│       ├── database/       # MongoDB connection
│       └── security/       # Input sanitization, credentials
├── docs/                   # Project documentation
├── requirements.txt
└── .env.example
```

## Getting Started

### Prerequisites

- Python 3.13.7
- MongoDB (running locally or remote URI)
- Groq API key (free: https://console.groq.com/keys) and/or NVIDIA NIM key (free: https://build.nvidia.com)
- Ollama with `mistral` model for local fallback (`ollama pull mistral`)

### Installation

```bash
# Clone the repo
git clone https://github.com/your-org/fivos-project.git
cd fivos-project

# Set up Python virtual environment
python3.13 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
playwright install

# Configure environment
cp .env.example .env
# Edit .env with your MongoDB URI and any other credentials
```

### Running the Dashboard

```bash
uvicorn app.main:app --port 8000
# Open http://localhost:8000
```

The dashboard provides:
- **Harvester** — Enter a URL or upload a .txt file to scrape and extract device data
- **Validator** — Compare harvested devices against FDA GUDID
- **GUDID Lookup** — Search the FDA database directly
- **Discrepancy Review** — Pick correct values for mismatched fields

### Running the Pipeline (Interactive Menu)

```bash
python harvester/src/pipeline/cli.py
```

This launches an interactive menu:
- **[1] Harvest Only** — Scrape URLs + extract with Ollama, output JSON files
- **[2] Harvest + Save to DB** — Scrape + extract + save to MongoDB
- **[3] Harvest + Save + Validate** — Full pipeline: scrape + extract + DB + GUDID validation
- **[0] Quit**

After selecting a mode, you choose Append or Overwrite for database writes.

### Running the Pipeline (CLI flags)

```bash
# Harvest only (scrape + extract to JSON, no DB)
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --no-validate

# Harvest + append to DB (default)
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --no-validate

# Harvest + overwrite DB (wipes devices collection first)
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite --no-validate

# Full pipeline: harvest → append to DB → validate against GUDID
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt

# Full pipeline with DB overwrite
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite

# Extract from existing HTML (no scrape)
python harvester/src/pipeline/runner.py --db --validate
```

### Running Tests

```bash
pytest                    # all tests
pytest -v                 # verbose
pytest harvester/src/pipeline/tests/  # pipeline tests only
```

## Key Features

- Automated scraping of manufacturer websites with retry logic and rate limiting
- LLM-powered extraction with 7-model fallback chain (Groq → NVIDIA → Ollama)
- Two-pass extraction: page-level fields + product table rows (one record per SKU)
- Comparison against FDA GUDID with per-field match scoring
- Web dashboard for human review of discrepancies
- Side-by-side field comparison with pick-the-correct-value workflow
- Append-by-default database writes (overwrite is CLI-only)
- Normalization for units, model numbers, dates, and text

## Team

| Name | Role |
|---|---|
| Wyatt Ladner | Developer |
| Jason Sonith | Developer |
| Ryan Tucker | Developer |
| Ralph Mouawad | Developer |
| Jonathan Gammill | Developer |

**Project Client:** Doug Greene, Fivos (doug.greene@fivoshealth.com)

## License

This project was built for Fivos as part of a senior design course. Contact the team or client for licensing details.
