# Fivos - Medical Device Data Harvesting & Validation

A multi-agent AI system that automates the process of checking medical device data between manufacturer websites and the FDA's GUDID database.

Built by **Vibe Coders** for [Fivos](https://www.fivoshealth.com) as a senior design project (CIS 497).

## The Problem

The FDA maintains a database called GUDID (Global Unique Device Identification Database) that is supposed to be the single source of truth for medical device information. In practice, the data in GUDID often does not match what manufacturers have on their own websites. Things like wrong dimensions, outdated brand names, or mismatched model numbers can cause real problems with patient records and equipment ordering.

This project automates most of that verification work.

## How It Works

**Collect → Compare → Correct**

**The Harvester** crawls manufacturer websites using Playwright and extracts device specs using an 8-model LLM fallback chain (gemma4 local → Groq → NVIDIA NIM → Ollama fallback). Extracted records are stored in MongoDB.

**The Validator** compares harvested records against the FDA's GUDID API — model numbers, catalog numbers, brand names, company names, and description similarity.

**The Review Dashboard** shows discrepancies side-by-side so human reviewers can pick the correct value for each mismatched field.

### Flow Diagram

```mermaid
flowchart LR
    USER([Admin / Reviewer]) -->|URLs| WEB[FastAPI Dashboard]
    WEB --> ORCH[Orchestrator]

    ORCH -->|scrape| PW[Playwright Scraper]
    MFG[/Manufacturer Sites/] -->|HTML| PW
    PW --> HTML[(out_html/)]

    HTML --> PARALLEL[parallel_batch<br/>ThreadPool × 4]
    PARALLEL --> LLM[LLM Chain<br/>gemma4 → Groq → NVIDIA<br/>per-provider semaphores]
    OLLAMA[/Ollama/] <--> LLM
    CLOUD[/Groq + NVIDIA/] <--> LLM
    LLM --> NORM[Normalize + Regulatory<br/>+ Record Validate]
    NORM --> DEVICES[(MongoDB<br/>devices)]

    DEVICES --> COMP[Comparison Validator]
    GUDID[/FDA GUDID API/] <--> COMP
    COMP --> VR[(MongoDB<br/>validationResults)]
    COMP -->|null-field merge| DEVICES

    VR --> WEB
    WEB -->|review + resolve| USER
```

See [`docs/Fivos - Data Flow Diagram.md`](docs/Fivos%20-%20Data%20Flow%20Diagram.md) for the full end-to-end DFD with auth, logging, and phase boundaries.

## Tech Stack

| Layer | Tools |
|---|---|
| Language | Python 3.13.7 |
| Web Scraping | Playwright (async, headless Chromium) |
| AI / LLM | Groq + NVIDIA NIM (cloud) → Ollama (local fallback) |
| Database | MongoDB |
| Web UI | FastAPI + Jinja2 |
| Auth | bcrypt + HIBP breach check |

## Project Structure

```
├── app/                    # FastAPI web dashboard
│   ├── routes/             # dashboard, harvester, validate, gudid, review, auth, admin
│   ├── services/           # auth_service, auth_guard, user_service
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS + JS (password.js)
├── harvester/src/
│   ├── pipeline/           # runner, llm_extractor, parallel_batch, parser, emitter, cli
│   ├── web_scraper/        # Playwright browser automation
│   ├── normalizers/        # text, model numbers, dates, units, booleans
│   ├── validators/         # GUDID client, comparison, record validation
│   ├── database/           # MongoDB connection
│   └── security/           # sanitization, credentials
└── docs/superpowers/specs/ # Design specs
```

## Getting Started

### Prerequisites

- Python 3.13.7, MongoDB, `bcrypt` (`pip install bcrypt`)
- Groq API key (free: console.groq.com) and/or NVIDIA NIM key (build.nvidia.com)
- Ollama with `gemma4` (primary), `qwen2.5:7b`, and `mistral`

### Installation

```bash
git clone <repo> && cd fivos-project
python3.13 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install
cp .env.example .env   # add FIVOS_MONGO_URI, GROQ_API_KEY, NVIDIA_API_KEY, AUTH_SECRET_KEY
```

### Running the Dashboard

```bash
uvicorn app.main:app --port 8000 --reload
# Open http://localhost:8000
```

On first start, demo accounts are seeded into MongoDB with `force_password_change: true`. Log in with `admin@fivos.local / admin123` — you'll be prompted to set a new password immediately (HIBP blocks reuse of `admin123`).

### Dashboard Pages

| Page | Route | Who |
|---|---|---|
| Dashboard | `/` | All |
| Harvester | `/harvester` | Admin |
| Validator | `/validate` | Admin |
| GUDID Lookup | `/gudid` | All |
| Review | `/review/<id>` | Admin, Reviewer |
| User Management | `/admin/users` | Admin only |

### Running the Pipeline (CLI)

```bash
python harvester/src/pipeline/cli.py                                    # interactive menu
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt   # full pipeline
python harvester/src/pipeline/runner.py --urls ... --no-validate         # harvest only
python harvester/src/pipeline/runner.py --urls ... --overwrite           # overwrite DB
```

### Running Tests

```bash
pytest        # all tests
pytest -v     # verbose
```

## Key Features

- LLM-powered extraction with 8-model fallback chain (gemma4 → Groq → NVIDIA → Ollama)
- Parallel batch extraction (4 workers) with per-provider concurrency caps and non-blocking fall-through — ~6× faster than sequential on 28-URL runs
- Two-pass extraction: page-level fields + product table rows (one record per SKU)
- 15 fields extracted per device including regulatory compliance (NRL, OTC, sterilization, deviceKit, 510k numbers)
- GUDID fallback merge: null harvested fields auto-filled from GUDID post-validation
- Comparison against FDA GUDID with per-field match scoring
- Human review dashboard: side-by-side field comparison, pick correct values
- MongoDB-backed auth with bcrypt (work factor 12) and HIBP k-anonymity breach check
- Admin account management: create accounts, set roles, disable/enable users
- Forced password change on first login for all new/seeded accounts

## Team

| Name | Role |
|---|---|
| Wyatt Ladner | Developer |
| Jason Sonith | Developer |
| Ryan Tucker | Developer |
| Ralph Mouawad | Developer |
| Jonathan Gammill | Developer |

**Client:** Doug Greene — doug.greene@fivoshealth.com
