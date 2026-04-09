# Fivos - Data Flow Diagram

End-to-end data flow for the Fivos medical device harvester: from a user request in the web dashboard through scraping, parallel LLM extraction, normalization, GUDID validation, and human review.

## Conventions

- `/Trapezoid/` — external entities (websites, APIs, users)
- `([Stadium])` — processes (code that transforms data)
- `[(Cylinder)]` — data stores (filesystem, MongoDB collections)
- `-->` — synchronous data flow
- `-.->` — logging / side-effect flow

## End-to-End Flow

```mermaid
flowchart TB
    %% ---- External entities ----
    subgraph External["External"]
        MFG[/"Manufacturer<br/>Websites"/]
        GUDID_API[/"FDA GUDID<br/>API v3"/]
        OLLAMA[/"Ollama<br/>localhost:11434"/]
        GROQ[/"Groq API"/]
        NVIDIA[/"NVIDIA NIM<br/>API"/]
        HIBP[/"HIBP<br/>k-anonymity"/]
        USER[/"Admin /<br/>Reviewer"/]
    end

    %% ---- Web layer ----
    subgraph Web["Web Layer — FastAPI"]
        AUTH([Auth Service<br/>bcrypt + HIBP])
        ROUTES([Routes: dashboard,<br/>harvester, validate,<br/>gudid, review, admin])
    end

    %% ---- Orchestration ----
    ORCH([Orchestrator])

    %% ---- Scraping ----
    subgraph Scrape["Phase 1 — Scrape"]
        SCRAPE([Playwright Scraper<br/>_scrape_urls_with_meta])
    end

    %% ---- Parallel extraction ----
    subgraph Extract["Phase 2 — Parallel Extraction (4 workers)"]
        PARALLEL([parallel_batch<br/>ThreadPoolExecutor])
        SANIT([Sanitize HTML])
        PARSE([BS4 Parse])
        LLM([LLM Extractor<br/>8-model chain<br/>per-provider semaphores<br/>ollama=1 groq=3 nvidia=4])
        REG([Regulatory Parser<br/>regex booleans])
        NORM([Normalizers<br/>text / model / date / units])
        VALID([Record Validator])
        EMIT([Emitter<br/>GUDID JSON])
    end

    %% ---- DB + validation ----
    subgraph Phase3["Phase 3 — DB Write + GUDID Validation"]
        DBWRITE([Device Insert])
        COMP([Comparison Validator<br/>per-field match + Jaccard])
        MERGE([GUDID Fallback Merge<br/>fill null fields])
    end

    %% ---- Data stores ----
    HTML_STORE[("web-scraper/out_html/<br/>raw HTML files")]
    JSON_STORE[("harvester/output/<br/>JSON records")]
    DEVICES[("MongoDB<br/>devices")]
    VR[("MongoDB<br/>validationResults")]
    USERS[("MongoDB<br/>users")]
    LOGS[("harvester/log-files/<br/>harvest_*.log")]

    %% ---- Auth flow ----
    USER -->|email + password| AUTH
    AUTH -->|SHA-1 prefix| HIBP
    AUTH <-->|lookup / update| USERS
    AUTH -->|session| ROUTES

    %% ---- Harvest trigger ----
    USER -->|URLs / batch upload| ROUTES
    ROUTES -->|run_harvest_batch| ORCH

    %% ---- Phase 1: Scrape ----
    ORCH -->|URL list| SCRAPE
    SCRAPE -->|HTTP GET| MFG
    MFG -->|HTML response| SCRAPE
    SCRAPE -->|write HTML| HTML_STORE
    SCRAPE -->|meta: url, path, error| ORCH

    %% ---- Phase 2: Parallel extract ----
    ORCH -->|paths + source_urls +<br/>progress_callback| PARALLEL
    HTML_STORE -->|HTML| PARALLEL
    PARALLEL -->|per worker| SANIT
    SANIT -->|safe HTML| PARSE
    PARSE -->|DOM + largest table| LLM
    LLM <-->|primary<br/>gemma4| OLLAMA
    LLM <-->|fall through| GROQ
    LLM <-->|fall through| NVIDIA
    LLM -->|warning_text| REG
    LLM -->|raw fields| NORM
    REG -->|regulatory booleans| NORM
    NORM -->|normalized record| VALID
    VALID -->|valid record| EMIT
    EMIT -->|JSON file| JSON_STORE
    EMIT -->|FileExtractionResult| PARALLEL
    PARALLEL -->|list of records| ORCH

    %% ---- Phase 3: DB + validation ----
    ORCH -->|records| DBWRITE
    DBWRITE -->|insert| DEVICES
    ORCH -->|run_validation| COMP
    DEVICES -->|by harvest_run_id| COMP
    COMP -->|DI search + lookup| GUDID_API
    GUDID_API -->|device record| COMP
    COMP -->|per-field scores| VR
    COMP -->|GUDID record| MERGE
    MERGE -->|fill null fields| DEVICES

    %% ---- Review flow ----
    USER -->|review / resolve| ROUTES
    ROUTES -->|fetch discrepancies| VR
    ROUTES -->|fetch device| DEVICES
    ROUTES -->|apply correction| DEVICES

    %% ---- Logging ----
    SCRAPE -.->|MainThread| LOGS
    LLM -.->|extract_0..3| LOGS
    COMP -.->|MainThread| LOGS
```

## Key flows explained

**Auth (every request).** User submits credentials to `ROUTES`. `AUTH` validates against the `users` collection using bcrypt. New passwords are checked against HIBP via client-side SHA-1 k-anonymity (only 5 hex chars leave the browser). Session cookies gate every other route; first-login accounts are forced through `/auth/change-password`.

**Phase 1 — Scrape.** `ORCH` calls `_scrape_urls_with_meta()`. Playwright fetches all URLs (internally batched with `max_concurrency=3`) and writes HTML files to `web-scraper/out_html/`. Returns per-URL metadata so failed scrapes are preserved in the results array.

**Phase 2 — Parallel extract.** `ORCH` delegates to `parallel_batch.process_html_files_parallel()` which spawns a `ThreadPoolExecutor(max_workers=4)`. Each worker reads one HTML file and runs the full pipeline: sanitize → parse → two-pass LLM extraction → regulatory parse → normalize → validate → emit. Inside `LLM`, each model attempts `sem.acquire(blocking=False)` on its provider semaphore (`ollama=1`, `groq=3`, `nvidia=4`); saturated workers fall through to the next model instead of queueing. Gemma4 stays at 1× (single GPU slot), overflow cascades to Groq → NVIDIA. Progress callback fires per completion.

**Phase 3 — DB write + validation.** All JSON records get inserted into the `devices` collection on the main thread. `COMP` then pulls devices by `harvest_run_id`, queries GUDID (search for DI → lookup by DI), compares four boolean fields plus Jaccard description similarity, writes per-device results to `validationResults`, and calls `MERGE` to backfill null device fields from the GUDID record (harvested always wins; GUDID-sourced fields tracked in `gudid_sourced_fields`).

**Review.** Reviewers pull partial-match and mismatch rows from `validationResults`, see side-by-side harvested-vs-GUDID values, and pick the correct value per field. Their choices overwrite the device document.

**Logging.** All phases log to `harvester/log-files/harvest_<timestamp>.log`. The format includes `[%(threadName)s]` — `[MainThread]` for orchestration, `[extract_0]` through `[extract_3]` for parallel workers — so interleaved lines remain readable.

## Related docs

- `docs/Fivos - Project Overview.md` — high-level project context
- `docs/superpowers/specs/2026-04-08-llm-extractor-parallelization-design.md` — parallelization design
- `docs/superpowers/specs/2026-04-04-gudid-field-expansion-design.md` — GUDID merge design
- `CLAUDE.md` — architecture and module map
