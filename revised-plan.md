# Fivos Integration Plan (Final Revised)

## Critique of Both Plans

### plan.md -- Strengths
- Excellent diagnosis of the "three islands" problem. Clear, accurate breakdown of what's disconnected.
- Thorough step-by-step breakdown (Phases 2-5) that covers every piece of the integration.
- Good "Who Does What" mapping that respects existing ownership.
- Correctly identifies the two-scraper naming problem (`web_scraper/` vs `web-scraper/`).

### plan.md -- Weaknesses
1. **Ordering bug.** Phase 2.4 says "replace local JSON storage with MongoDB reads" but Phase 3 is where records actually get *written* to MongoDB. You'd be reading from an empty database. plan-2.md correctly caught this.
2. **Recommends Option C (merge UIs)** -- this is the most work for the least clarity. Merging two server-side rendered FastAPI apps with different template structures, different routing patterns, and different data sources is effectively a rewrite. The plan underestimates this.
3. **No orchestration layer.** Each phase wires things point-to-point: the UI calls the scraper service, which calls the pipeline, which calls MongoDB, which calls the validator. This creates spaghetti coupling. If any step changes, you're editing 3 files.
4. **No async strategy.** Scraping + pipeline can take 10-30 seconds. The plan never addresses what happens to the HTTP request during that time. The browser would just hang.
5. **Credentials fix buried at priority #4.** The MongoDB password (`Fivos`) is in plaintext in committed code. This should be priority #0, not #4.
6. **No integration tests.** The plan goes from "wire everything" to "batch operations" with no step to prove the chain actually works.
7. **Pipeline purity violated.** Phase 3.1 adds MongoDB inserts directly into `runner.py`. This couples the pure transformation pipeline to a specific database, making it harder to test and reuse.
8. **Batch ops (Phase 6) treated as core.** For a senior project demo, batch harvesting is a nice-to-have, not a must-have. The plan doesn't distinguish.

### plan-2.md -- Strengths
1. **Fixes the ordering bug.** Orchestrator writes to MongoDB (Phase 2) before the UI reads from it (Phase 3.5).
2. **Adds an orchestration layer** (`orchestrator.py`) -- single entry point, clean separation. Pipeline stays pure, orchestrator owns persistence. This is the right architecture.
3. **Correct UI recommendation.** Option B (Interface.py) saves significant work. Auth, review queue, and audit trail are hard features that already exist. Adding a harvester form to Interface.py is straightforward. plan-2.md is right that "merge" is just "rewrite with extra steps."
4. **Credentials as Phase 0.** Correct urgency.
5. **Async handling.** BackgroundTasks + polling is the simplest pattern that works with server-side rendering. No WebSockets needed.
6. **Integration tests as an explicit phase.** Three specific tests with a test database.
7. **Ollama health check early.** Handles the case where the LLM server is down before it becomes a demo-day surprise.
8. **Batch ops explicitly marked as stretch.** Realistic scoping.

### plan-2.md -- Weaknesses
1. **Recommends Interface.py (Option B) but the UI is significantly worse.** Interface.py uses in-memory mocks for everything -- runs, logs, discrepancies are all fake Python dicts. The auth system is also in-memory (hardcoded users dict). "It already has auth" is generous; it has the *skeleton* of auth. The actual effort gap between the two options is smaller than plan-2.md suggests.
2. **Underestimates the Interface.py rework.** Interface.py needs: real MongoDB queries replacing every mock, a harvester form + route, a results page, adapter selection, restyling. That's close to the same amount of work as adding auth + review to `app/`.
3. **No mention of the `data/` directory cleanup.** The normalized_records.json is already deleted (per git status), but raw_records.json and the directory structure are still there. Minor but should be tracked.
4. **Orchestrator pseudocode mixes sync and async.** `run_harvest` uses `await fetch_page_html()` (async) but is shown as a regular function. This matters because FastAPI route handlers need to know whether to `await` or use `run_in_executor`. Needs clarity on whether the orchestrator is sync or async.

---

## Verdict: plan-2.md is the better plan

plan-2.md fixes real architectural problems in plan-1.md (ordering, orchestration layer, pipeline purity, async handling, test coverage, credential urgency). The improvements aren't cosmetic -- they change how the system is structured. The orchestrator pattern alone justifies picking plan-2.md.

**However, I disagree with plan-2.md's UI recommendation.** The rest of the revised plan below follows plan-2.md's structure with that one correction and a few additions.

---

## Final Plan

### Phase 0: Security Fix (Do First)

**Owner: Jason. Time: 30 minutes.**

1. Rotate the MongoDB Atlas password (the current one, `Fivos`, is in git history forever)
2. Rewrite `db_connection.py` to use `CredentialManager.get_db_uri()` from `security/credentials.py`
3. Add `FIVOS_MONGO_URI` to `.env.example`
4. Confirm `.env` is in `.gitignore`

This is non-negotiable. A plaintext password in a public repo is a live vulnerability.

---

### Phase 1: Pick One UI

**Owner: Team decision. Must happen before Phase 3.**

**Recommendation: Option A (`app/`).** Here's why:

| Factor | `app/` | `Interface.py` |
|--------|--------|----------------|
| UI quality | Polished dark theme, responsive, 4 working pages | Basic/unstyled, functional but rough |
| Real data | Reads local JSON (must switch to MongoDB) | Reads in-memory mocks (must switch to MongoDB) |
| Auth | None (must add) | In-memory hardcoded users dict (must rewrite for real auth anyway) |
| Review workflow | None (must add) | Has skeleton with in-memory mocks (must rewrite for MongoDB) |
| Audit trail | None (must add) | Logs to in-memory list (must rewrite for MongoDB) |
| Harvester form | Has one (needs real wiring) | None (must add) |
| Normalize/Results | Has both pages | None |

The key insight: Interface.py's "existing" auth and review features are all backed by in-memory mocks. They need to be rewritten against MongoDB regardless of which UI you pick. Once you factor in that rewrite, the effort gap narrows significantly. Meanwhile, `app/` has 4 working pages with a polished UI that would take real effort to replicate.

**Pick `app/`, add the review/auth features from Interface.py's logic as you go.** It's the same amount of backend work either way -- you might as well start with the better-looking shell.

If the team strongly prefers Interface.py's workflow-first approach, that's fine too. The architecture (orchestrator pattern) works with either choice.

---

### Phase 2: Build the Orchestration Layer

**Owner: Jason (pipeline) + Ralph (DB). Time: 1-2 days.**

Create `harvester/src/orchestrator.py` -- a single coordination layer between the UI and everything else.

Two functions:

**`async run_harvest(url, adapter_path, run_id) -> dict`**
1. Scrape the URL (async, via `BrowserEngine.fetch`)
2. Save HTML to temp file
3. Run `process_single(html_path, adapter)` -- pipeline stays pure, no DB coupling
4. Insert result into MongoDB `devices` collection
5. Return `{"success": True, "record": record}` or `{"success": False, "error": "..."}`

**`run_validation(run_id=None) -> dict`**
1. Health-check Ollama (`GET http://localhost:11434/api/tags`) -- if down, return clear error
2. Call `run_validator()` with optional run_id filter (don't re-validate everything)
3. Return structured results

Key principle: **pipeline stays pure.** `runner.py` does HTML-in, dict-out. The orchestrator handles persistence. This keeps the pipeline testable and reusable.

Also in this phase:
- Consolidate `web-scraper/` (hyphen) and `web_scraper/` (underscore) into one directory (`web_scraper/`)
- Clean up `data/raw/` and `data/normalized/` (local JSON no longer needed)

---

### Phase 3: Wire the UI to the Orchestrator

**Owner: Jonathan (UI) + Wyatt (scraper). Time: 2-3 days.**

#### 3.1 -- Adapter selection
- Scan `harvester/src/site_adapters/` at startup, build list of available adapters
- Add dropdown to harvester form: "Select adapter" (e.g., "Medtronic - table_wrapper_layout")

#### 3.2 -- Wire "Run Harvest"
- Replace placeholder logic in `app/routes/harvester.py`
- Call `orchestrator.run_harvest(url, adapter_path, run_id)`
- Display the real extracted record

#### 3.3 -- Handle long-running operations
Scraping takes 10-30 seconds. Use FastAPI `BackgroundTasks`:
- Route starts the job, redirects to a "Processing..." page
- Job writes status to a MongoDB `jobs` collection
- Processing page polls `GET /job/{id}/status` every 2 seconds
- When complete, redirect to results

No WebSockets needed. Works with server-side rendering.

#### 3.4 -- Wire "Run Validation"
- Add route: `POST /validate`
- Call `orchestrator.run_validation(run_id)`
- If Ollama is down, show: "Local LLM server not running. Start Ollama to enable GUDID comparison."

#### 3.5 -- Wire all pages to MongoDB
- Dashboard stats: `devices.count_documents()`, `validationResults.count_documents()`
- Results page: query `devices`, display records
- Validation results: query `validationResults`, show match/mismatch per field
- `/normalize` page: show records that have already been normalized by the pipeline (normalization is baked into the pipeline, not a separate step)

#### 3.6 -- Delete dead code
- Remove `app/services/scraper_service.py` (replaced by orchestrator)
- Remove `app/services/normalization_service.py` (pipeline does this internally)
- Remove `app/services/storage_service.py` (MongoDB replaces local JSON)

---

### Phase 4: Integration Tests

**Owner: Jason + Ryan. Time: 1 day.**

Write 2-3 integration tests using a test database (`fivos-test`):

1. **Harvest test:** Saved HTML + adapter YAML -> `orchestrator.run_harvest()` -> assert record in MongoDB with expected fields
2. **Validation test:** Known device in MongoDB -> `orchestrator.run_validation()` -> assert validation result created (skip Ollama if unavailable, test record-level validation)
3. **End-to-end smoke test:** Harvest a real URL (pick one stable page), validate, check that a result appears

---

### Phase 5: Review Workflow

**Owner: Jonathan + Ryan. Time: 2-3 days.**

Port the review/auth concepts from Interface.py into `app/`:

#### 5.1 -- Review page
- New route: `GET /review`
- Query `validationResults` where status is not `matched`
- For each discrepancy: show harvested value vs GUDID value
- Reviewer picks: "Accept Harvested", "Accept GUDID", or "Override with custom value"
- On submit: update `devices` collection, mark as reviewed

#### 5.2 -- Audit trail
- `reviewAudit` collection in MongoDB
- Fields: who, when, device_id, field, old_value, new_value, decision
- Viewable from dashboard

#### 5.3 -- Basic auth
- Session-based login (admin, reviewer roles)
- Protect review routes behind reviewer role
- Port the role logic from Interface.py, but back it with MongoDB instead of in-memory dict

---

### Phase 6: Polish (Time Permitting)

**Owner: Whole team. Only after Phases 0-4 are done.**

- **Run summaries:** Call `build_runs.py` logic from orchestrator after harvest completes
- **Run history page:** Dashboard shows past runs with record count, pass/fail
- **Batch harvesting (stretch):** Select multiple adapters, kick off all, show per-adapter status. Only attempt if everything else is solid.

---

## Priority Summary

| Priority | Phase | Effort | Why this order |
|----------|-------|--------|----------------|
| **0** | Security fix | 30 min | Password is exposed. Do it now. |
| **1** | Pick a UI | Team call | Unblocks all integration work |
| **2** | Orchestration layer | 1-2 days | Single entry point for the whole flow |
| **3** | Wire UI to orchestrator | 2-3 days | System becomes usable end-to-end |
| **4** | Integration tests | 1 day | Prove it works before demo |
| **5** | Review workflow | 2-3 days | Completes "Collect, Compare, Correct" loop |
| **6** | Polish + batch | Remaining time | Nice-to-haves for demo day |

---

## Who Does What

| Phase | Owner | Why |
|-------|-------|-----|
| Phase 0 | **Jason** | Owns security, 30-minute fix |
| Phase 1 | **Team** | Needs alignment |
| Phase 2 | **Jason** + **Ralph** | Jason owns pipeline, Ralph owns database |
| Phase 3 | **Jonathan** + **Wyatt** | Jonathan owns frontend, Wyatt owns scraper |
| Phase 4 | **Jason** + **Ryan** | Pipeline + validator testing |
| Phase 5 | **Jonathan** + **Ryan** | UI + validation logic |
| Phase 6 | **Everyone** | Polish sprint |

---

## TL;DR

plan-2.md is the better plan. This revised plan follows its structure (orchestrator pattern, credential urgency, integration tests, pipeline purity) but recommends `app/` over Interface.py for the UI, since Interface.py's "existing" features are all in-memory mocks that need rewriting anyway. Start with the better-looking shell, add the real backend.
