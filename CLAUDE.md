# CLAUDE.md

## Project Overview

**Fivos** is a multi-agent AI system that harvests medical device data from manufacturer websites and validates it against the FDA's GUDID database, flagging discrepancies for human review.

- **Client**: Doug Greene — doug.greene@fivoshealth.com — Fivos, 8 Commerce Ave, West Lebanon, NH 03784
- **Team**: Vibe Coders (CIS 497 Senior Design) — started 1/15/2026
- **Python version**: 3.13.7
- **Workflow**: "Collect → Compare → Correct" with AI feedback loop

**Data flow by owner:** Jonathan (orchestration) → Wyatt (scraping) → Ryan (adapters) → Jason (pipeline + security) → Ralph (storage)

## Commands

```bash
pip install -r requirements.txt && playwright install   # Install
pytest                                                   # All tests
python harvester/src/pipeline/cli.py                     # Interactive CLI menu
uvicorn app.main:app --port 8000                         # Web dashboard
```

### Pipeline CLI (`harvester/src/pipeline/runner.py`)

```bash
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt            # Full pipeline (scrape→extract→DB→validate)
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite # Full pipeline, overwrite DB
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --no-validate # Harvest only, no GUDID check
python harvester/src/pipeline/runner.py                                          # Extract from existing HTML
python harvester/src/pipeline/runner.py --input <html> --adapter <yaml>          # Single file with CSS adapter
```

## Environment
Copy `.env.example` → `.env`. Required: `FIVOS_MONGO_URI`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `AUTH_SECRET_KEY`.

## Architecture

```
Manufacturing Website → Playwright scraper → Raw HTML (web-scraper/out_html/)
  → LLM extraction (8-model fallback chain) → normalize → validate → GUDID JSON (harvester/output/)
  → MongoDB (devices) → GUDID API validation → Review Dashboard (FastAPI)
```

### LLM Fallback Chain (`pipeline/llm_extractor.py`)

```
1. Ollama gemma4                        (local primary, 9.6GB)
2. Groq   llama-3.3-70b-versatile       (fastest cloud, 100k TPD limit)
3. Groq   llama-3.1-8b-instant          (separate Groq limits)
4. NVIDIA meta/llama-3.3-70b-instruct   (40 RPM, generous limits)
5. NVIDIA mistralai/mistral-large       (40 RPM)
6. NVIDIA google/gemma-2-27b-it         (40 RPM)
7. Ollama qwen2.5:7b                    (local fallback)
8. Ollama mistral                       (local fallback)
```

Tries top-to-bottom. On rate limit < 60s: retries once. On daily limit or long wait: disables model for session, moves to next. Groq/NVIDIA use same OpenAI-compatible `_openai_request()`. Ollama uses `/api/chat`.

**Parallel batch mode:** `ThreadPoolExecutor(max_workers=4)` runs multiple files through the chain concurrently via `pipeline/parallel_batch.py`. Each model has a per-provider semaphore (`OLLAMA_CONCURRENCY=1`, `GROQ_CONCURRENCY=3`, `NVIDIA_CONCURRENCY=4`) acquired non-blocking — workers fall through to the next model when a provider is saturated instead of queueing. Gemma4 stays at 1× (GPU-bound), overflow cascades to Groq → NVIDIA. Thread-safety: `_last_model_used` is `threading.local()`, `_disabled_models` writes are locked.

### Extraction (Two-Pass)

1. **Pass 1 (page-level):** device_name, manufacturer, description, warning_text, MRISafetyStatus, deviceKit, premarketSubmissions, environmentalConditions. Regulatory text also yields: singleUse, rx, deviceSterile, labeledContainsNRL, labeledNoNRL, sterilizationPriorToUse, otc.
2. **Pass 2 (product rows):** model_number, catalog_number, dimensions from largest table. One GUDID record per SKU.

### Web Dashboard Pages

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/` | Stats + discrepancy review queue |
| Harvester | `/harvester` | Single URL or batch .txt upload → scrape + extract + DB |
| Validator | `/validate` | GUDID validation, per-field match/mismatch table |
| GUDID Lookup | `/gudid` | Direct FDA API query |
| Review | `/review/<id>` | Side-by-side field comparison, pick correct value |
| User Management | `/admin/users` | Admin only — create accounts, set roles, disable/enable |
| Change Password | `/auth/change-password` | Forced on first login; blocks all other routes until done |

### Module Map

- `pipeline/` — runner, llm_extractor, parallel_batch, parser, extractor, dimension_parser, regulatory_parser, emitter, cli
- `normalizers/` — text, model_numbers, dates, unit_conversions, booleans
- `validators/` — gudid_client, comparison_validator, record_validator
- `security/` — Input sanitization, credential management
- `database/` — MongoDB connection (`db_connection.py`)
- `web_scraper/` — Playwright browser automation
- `site_adapters/` — YAML CSS selector configs (optional `--adapter` override)
- `app/routes/` — dashboard, harvester, validate, gudid, review, auth, admin
- `app/services/` — auth_service, auth_guard, user_service (bcrypt + HIBP)
- `app/static/js/password.js` — client-side HIBP k-anonymity + strength meter

### Key Components

| Component | Role | Triggered by |
|-----------|------|-------------|
| **Web Scraper** (`web_scraper/scraper.py`) | Playwright HTML fetcher | `runner.py --urls` |
| **LLM Extractor** (`pipeline/llm_extractor.py`) | Primary extractor, 7-model chain | Every file in pipeline |
| **Site Adapters** (`site_adapters/*.yaml`) | CSS selectors, optional override | `--adapter` flag only |
| **Pipeline** (`pipeline/runner.py`) | End-to-end orchestration | CLI or web UI |

### Logging

All pipeline logs go to `harvester/log-files/harvest_<timestamp>.log`. No console logging during CLI execution — only status lines and results. Log format includes `[%(threadName)s]` so parallel-worker lines (`[extract_0]`, `[extract_1]`, …) are distinguishable from `[MainThread]`.

### Validation Scoring

`comparison_validator.py` compares on 4 boolean fields (`versionModelNumber`, `catalogNumber`, `brandName`, `companyName`) + `description_similarity` Jaccard score. `None` fields are skipped (not counted as mismatches).

### GUDID Fallback Merge

After validation, `_merge_gudid_into_device()` in `orchestrator.py` fills null device fields from GUDID values (16 tracked fields). Harvested wins if present. GUDID-sourced fields recorded in `gudid_sourced_fields` on each device document.

## Error Handling: "Never crash the run"

- Parsing failure → log + skip record
- Extraction failure → log + try next model in chain + skip if all fail
- Normalization failure → keep raw value in `raw_*` field
- Validation failure (critical) → reject; (non-critical) → emit with issues list

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser automation | Playwright + asyncio |
| HTML parsing | BeautifulSoup4 + lxml |
| Database | MongoDB |
| Validation | FDA GUDID API v3 |
| Web UI | FastAPI + Jinja2 (light mode, Fira Sans/Fira Code) |
| Auth | bcrypt (work factor 12) + HIBP k-anonymity breach check |
| AI | Groq + NVIDIA NIM (cloud) → Ollama (local fallback) |

## Docs

- `docs/Fivos - Project Overview.md` — High-level project overview
- `docs/Team Roles -Harvester Agent.md` — Team roles
- `docs/Jason - Todo.md` — Jason's todo list
- `docs/Target Brands.xlsx` — Target manufacturer brands
