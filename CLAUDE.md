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
python run.py                                            # Web dashboard (http://localhost:8500)
```

### Docker (full stack)

Compose files live in `docker/` — `cd docker` first, or pass `-f docker/docker-compose.yml` from root.

```bash
cd docker
docker compose up                    # Start app + mongo + ollama + model download
docker compose up -d                 # Same, detached
docker compose down                  # Stop (keeps volumes)
docker compose down -v               # Stop + wipe volumes (forces model re-download)
docker compose logs -f app           # Tail FastAPI logs
docker compose exec app bash         # Shell into app container
```

First run downloads `gemma4:e4b` into the `ollama_models` named volume via the `ollama-init` sidecar. The local `gemma4:e4b` is the primary extractor; cloud LLMs (Groq, NVIDIA) absorb overflow and serve as fallback. GPU passthrough is opt-in via `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up` (requires NVIDIA Container Toolkit).

### Pipeline CLI (`harvester/src/pipeline/runner.py`)

```bash
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt            # Full pipeline (scrape→extract→DB→validate)
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --overwrite # Full pipeline, overwrite DB
python harvester/src/pipeline/runner.py --urls harvester/src/urls.txt --no-validate # Harvest only, no GUDID check
python harvester/src/pipeline/runner.py                                          # Extract from existing HTML
python harvester/src/pipeline/runner.py --input <html> --adapter <yaml>          # Single file with CSS adapter
```

## Environment
Copy `.env.example` → `.env`. Required: `FIVOS_MONGO_URI`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `AUTH_SECRET_KEY`. Optional: `OLLAMA_URL` (defaults to `http://localhost:11434/api/chat`; compose overrides to `http://ollama:11434/api/chat`), `UVICORN_RELOAD` (default `false`; set to the literal string `true`, case-insensitive, for local dev auto-reload — `1`, `yes`, `on` do not work).

In Docker, compose overrides `OLLAMA_URL` → `http://ollama:11434/api/chat`. `FIVOS_MONGO_URI` and the rest of `.env` are injected from the project-root `.env` via `env_file`. The stack points at MongoDB Atlas; there is no local mongo service.

## Architecture

```
Manufacturing Website → Playwright scraper → Raw HTML (web-scraper/out_html/)
  → LLM extraction (5-model fallback chain) → normalize → validate → GUDID JSON (harvester/output/)
  → MongoDB (devices) → GUDID API validation (8-worker parallel, 24h disk cache) → Review Dashboard (FastAPI)
```

### LLM Fallback Chain (`pipeline/llm_extractor.py`)

```
1. Ollama gemma4:e4b                    (primary, most capable per user judgment)
2. NVIDIA mistralai/mistral-large       (~123B, strongest cloud)
3. Groq   llama-3.3-70b-versatile       (70B, fastest provider)
4. NVIDIA meta/llama-3.3-70b-instruct   (70B, slower-provider backup)
5. Groq   llama-3.1-8b-instant          (8B, last resort)
```

Local-first: gemma4:e4b is primary; cloud models absorb overflow when the Ollama semaphore is saturated and serve as fallback when the local model fails. Tries top-to-bottom. On rate limit < 60s: retries once. On daily limit or long wait: disables model for session, moves to next. Groq/NVIDIA use same OpenAI-compatible `_openai_request()`. Ollama uses `/api/chat`.

**Parallel batch mode:** `ThreadPoolExecutor(max_workers=4)` runs multiple files through the chain concurrently via `pipeline/parallel_batch.py`. Each model has a per-provider semaphore (`OLLAMA_CONCURRENCY=1`, `GROQ_CONCURRENCY=3`, `NVIDIA_CONCURRENCY=4`) acquired non-blocking — workers fall through to the next model when a provider is saturated instead of queueing. Local gemma4:e4b absorbs roughly 1 of every 4 batched files; cloud workers handle the rest. Ollama stays at 1× for CPU-safe hosts. Thread-safety: `_last_model_used` is `threading.local()`, `_disabled_models` writes are locked.

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
| **LLM Extractor** (`pipeline/llm_extractor.py`) | Primary extractor, 5-model chain | Every file in pipeline |
| **Site Adapters** (`site_adapters/*.yaml`) | CSS selectors, optional override | `--adapter` flag only |
| **Pipeline** (`pipeline/runner.py`) | End-to-end orchestration | CLI or web UI |

### Logging

All pipeline logs go to `harvester/log-files/harvest_<timestamp>.log`. No console logging during CLI execution — only status lines and results. Log format includes `[%(threadName)s]` so parallel-worker lines (`[extract_0]`, `[extract_1]`, …) are distinguishable from `[MainThread]`.

### Validation Scoring

`comparison_validator.py` returns `(per_field, summary)`. Per-field `status` is one of six values: `match` / `mismatch` / `corporate_alias` / `not_compared` / `both_null` / `sku_label_skip`. Compared fields:

- **Identifier (weight 3):** `versionModelNumber`, `catalogNumber`, `brandName`, `companyName`, `gmdnPTName`, `productCodes` (subset match)
- **Enum / regulatory (weight 2):** `MRISafetyStatus`, `singleUse`, `rx`, `gmdnCode`, `deviceCountInBase`, `issuingAgency`, `premarketSubmissions` (subset)
- **Labeling (weight 1):** `lotBatch`, `serialNumber`, `manufacturingDate`, `expirationDate`, `deviceDescription` (Jaccard, quality-gated)

Scoring produces both `match_percent` (unweighted count) and `weighted_percent` (using FIELD_WEIGHTS). Status thresholds (`matched`/`partial_match`/`mismatch`) drive from unweighted only; weighted is display + audit.

Corporate-alias match on `companyName` resolves via `company_aliases.py` — six seed parent groups (Medtronic, Boston Scientific, BD, Abbott, Johnson & Johnson, Stryker). Alias matches count +1 toward both numerator and denominator.

GUDID deactivated short-circuit: when `deviceRecordStatus == "Deactivated"`, validation skips comparison and records `status: "gudid_deactivated"`. No merge, no verified_devices.

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
| AI | Ollama gemma4:e4b (local primary) → Groq + NVIDIA NIM (cloud overflow + fallback) |

## Docs

- `docs/Fivos - Project Overview.md` — High-level project overview
- `docs/Fivos - Data Flow Diagram.md` — End-to-end DFD with auth, logging, phase boundaries
- `docs/Fivos - ZAP Scan Vulnerability Report.pdf` — OWASP ZAP baseline scan results (58 PASS, 0 FAIL)
- `docs/Target Brands.xlsx` — Target manufacturer brands
