# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Fivos** is a multi-agent AI system that harvests medical device data from manufacturer websites and validates it against the FDA's GUDID database, flagging discrepancies for human review.

- **Client**: Doug Greene — doug.greene@fivoshealth.com — Fivos, 8 Commerce Ave, West Lebanon, NH 03784
- **Team**: Vibe Coders (CIS 497 Senior Design) — started 1/15/2026
- **Python version**: 3.13.7
- **Workflow**: "Collect → Compare → Correct" with AI feedback loop

**Data flow by owner:** Jonathan (orchestration) → Wyatt (scraping) → Ryan (adapters) → Jason (pipeline + security) → Ralph (storage)

## Commands

```bash
# Install
pip install -r requirements.txt
playwright install

# Test
pytest                                    # all tests
pytest harvester/src/pipeline/tests/test_pipeline_e2e.py  # single file
pytest harvester/src/normalizers/tests/test_units.py::TestWeightConversions::test_kg_to_g  # single test

# Run pipeline
python harvester/src/pipeline/runner.py --adapter-dir harvester/src/site_adapters --input-dir harvester/src/web-scraper/out_html  # batch
python harvester/src/pipeline/runner.py --adapter <yaml> --input <html>  # single file
# Options: --output-dir DIR, --run-id HR-10011, -v

# Dashboard
uvicorn harvester.src.Interface.Interface:app --port 8000
```

## Environment
Copy `.env.example` → `.env` and fill in credentials before running.
Required vars are listed in `.env.example`.

## Architecture

```
Site Adapters                    Manufacturing Website
(Config Files)                          ^
        |                               | Page Requests
        | Scraping Rules                |
        v                               |
   Web Scraper  ─────────────────────────
        |
        | Raw HTML File
        v
  Normalization Pipeline
        |
        | Normalized Files
        v
  MongoDB ◄─────────────────────────────────────────┐
  (Harvested Data)                                  |
        |                                    Update Records
        |                                           |
        └──────────────────────────────────────┐    |
  FDA GUDID Database                           |    |
  (Reference Data)                             |    |
        |                                      v    |
        | Compare              ──────> Validator Agent
        └──────────────────────                |
                                               | Flagged Discrepancies
                                               v
                                        Review Dashboard
                                               |
                                               └──────────────────────┘
```

**Other modules:** `security/` (input sanitization, credential handling) · `validators/` (GUDID record validation) · `database/` (MongoDB import/build utilities)

## Error Handling Philosophy: "Never crash the run"

- Parsing failure → log + store raw HTML + skip record
- Extraction failure → log per missing field + emit partial if required fields present
- Normalization failure → keep raw value in `raw_*` field + flag for review
- Validation failure (critical) → reject + log; (non-critical) → emit with issues list

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser automation | Python + Playwright + asyncio |
| HTML parsing | BeautifulSoup4 + lxml |
| Site adapters | YAML/JSON config files |
| Data lake | MongoDB (NoSQL) |
| Validation DB | PostgreSQL |
| Web UI | FastAPI (current); React/Next.js (planned) |
| AI (local) | Ollama (open source, runs locally) |
| Source control | Git / GitHub |

## Detailed Documentation

For deeper context, reference these files as needed:

- `docs/Fivos Multi-Agent AI System for Automated Medical Device Data Harvesting and Regulatory Validation` — High level overview of the project.
- `docs/Team Roles -Harvester Agent.md` - For roles of the project, who does what, etc.
- `docs/Jason - Todo.md` - Jason's todo list.
- `docs/Target Brands.xlsx` - Brands that we are scraping the manufacturing websites for.
- `docs/Fivos System Architecture Diagram.md` - Architecture of our entire system.

