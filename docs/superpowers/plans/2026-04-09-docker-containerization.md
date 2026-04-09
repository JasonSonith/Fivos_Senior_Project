# Docker Containerization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker compose up` a one-command start for the full Fivos stack (FastAPI + harvester + Playwright + MongoDB + GPU-accelerated Ollama with all three required models auto-downloaded).

**Architecture:** Four-service Compose stack. `app` uses the official Playwright Python image and installs Chromium. `mongo` adds a healthcheck. `ollama` uses the official image with NVIDIA GPU passthrough. A one-shot `ollama-init` sidecar pulls `gemma4:latest`, `qwen2.5:7b`, and `mistral` into a named volume on first run. Two tiny code edits make `OLLAMA_URL` and the uvicorn reload flag env-driven so local dev keeps working unchanged.

**Tech Stack:** Docker Compose v2, `mcr.microsoft.com/playwright/python:v1.47.0-jammy`, `mongo:7`, `ollama/ollama:latest`, NVIDIA Container Toolkit, Python 3.11, pytest, FastAPI, Uvicorn.

**Spec reference:** `docs/superpowers/specs/2026-04-09-docker-containerization-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `harvester/src/pipeline/llm_extractor.py` | Modify line 17 | Read `OLLAMA_URL` from env, default to localhost for local dev |
| `harvester/src/pipeline/tests/test_llm_extractor_env.py` | **Create** | Test that `OLLAMA_URL` respects env var override |
| `run.py` | Modify | Read `UVICORN_RELOAD` from env instead of hardcoding `True` |
| `.dockerignore` | **Create** | Keep build context lean, block secrets |
| `Dockerfile` | Rewrite | Playwright base image + Chromium + pip install |
| `docker-compose.yml` | Rewrite | 4 services (app, mongo, ollama, ollama-init) + volumes + healthcheck + GPU |
| `README.md` | Modify | New "Docker Setup" section |
| `CLAUDE.md` | Modify | Add Docker commands and env vars to the Commands section |

**Task order rationale:** Code changes first (TDD), then `.dockerignore`, then Dockerfile, then compose, then end-to-end verification, then docs. Code before infra so the container has working code to run; docs last so they reflect what actually got built.

---

## Task 1: Env-driven `OLLAMA_URL`

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py:17`
- Create: `harvester/src/pipeline/tests/test_llm_extractor_env.py`

- [ ] **Step 1: Write the failing test**

Create `harvester/src/pipeline/tests/test_llm_extractor_env.py`:

```python
import importlib
import os


def test_ollama_url_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    import harvester.src.pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)
    assert llm_extractor.OLLAMA_URL == "http://localhost:11434/api/chat"


def test_ollama_url_respects_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/api/chat")
    import harvester.src.pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)
    assert llm_extractor.OLLAMA_URL == "http://ollama:11434/api/chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest harvester/src/pipeline/tests/test_llm_extractor_env.py -v`

Expected: `test_ollama_url_respects_env_override` FAILS because `OLLAMA_URL` is hardcoded to `http://localhost:11434/api/chat` regardless of env.

- [ ] **Step 3: Make the change in `llm_extractor.py`**

In `harvester/src/pipeline/llm_extractor.py`, change line 17 from:

```python
OLLAMA_URL = "http://localhost:11434/api/chat"
```

to:

```python
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
```

Note: `import os` is already present on line 3 and `load_dotenv()` is already called on line 11, so env vars from `.env` are picked up automatically.

- [ ] **Step 4: Run tests to verify both pass**

Run: `pytest harvester/src/pipeline/tests/test_llm_extractor_env.py -v`

Expected: both tests PASS.

- [ ] **Step 5: Run the full pipeline test suite to catch regressions**

Run: `pytest harvester/src/pipeline/tests/ -q`

Expected: all tests pass (should be 384+ tests, matching the baseline from the 2026-04-08 parallelization work).

- [ ] **Step 6: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py harvester/src/pipeline/tests/test_llm_extractor_env.py
git commit -m "feat: make OLLAMA_URL env-driven for container support

Read OLLAMA_URL from environment with localhost fallback so the same
code runs both locally and inside a container where Ollama is a peer
service, not a localhost process."
```

---

## Task 2: Env-gated uvicorn reload flag

**Files:**
- Modify: `run.py`

No test: `run.py` is a 3-line entry point with no importable logic. It's verified end-to-end by Task 8 (container smoke test).

- [ ] **Step 1: Rewrite `run.py`**

Replace the entire contents of `/mnt/c/Users/sonit/Github/Fivos_Senior_Project/run.py` with:

```python
import os

import uvicorn

if __name__ == "__main__":
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    print("Server running at http://localhost:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=reload)
```

- [ ] **Step 2: Verify local dev behavior still works (manual)**

Run: `UVICORN_RELOAD=true python run.py`

Expected: server starts with reload enabled. Visit `http://localhost:8000` in browser, confirm it responds. Ctrl-C to stop.

Then run: `python run.py`

Expected: server starts *without* reload (no "Started reloader process" line). Visit `http://localhost:8000`, confirm it responds. Ctrl-C to stop.

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat: gate uvicorn reload behind UVICORN_RELOAD env var

Containers should run without reload (causes restart loops on read-only
layers). Local dev can opt in by exporting UVICORN_RELOAD=true."
```

---

## Task 3: `.dockerignore`

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create the file**

Create `/mnt/c/Users/sonit/Github/Fivos_Senior_Project/.dockerignore` with these contents:

```
.git
.gitignore
.github
__pycache__
*.pyc
*.pyo
.venv
venv
env
.env
.env.local
node_modules
.vscode
.idea
*.log
harvester/log-files/
harvester/output/
web-scraper/out_html/
docs/
*.md
!README.md
plan.md
```

Why each entry:
- `.git`, `.github`, `.vscode`, `.idea`, `node_modules` — tooling, not runtime code
- `__pycache__`, `*.pyc`, `*.pyo`, `.venv`, `venv`, `env` — Python build artifacts / local virtualenvs
- `.env`, `.env.local` — **secrets never enter the image**; compose injects at runtime via `env_file`
- `*.log`, `harvester/log-files/`, `harvester/output/`, `web-scraper/out_html/` — runtime data, not source
- `docs/` — design docs, plans, specs; runtime code does not need them
- `*.md` with `!README.md` — exclude all markdown except README (CLAUDE.md files are excluded by this rule intentionally; they are only useful during development, not at runtime)
- `plan.md` — old planning file at repo root (per 2026-03-30 changelog)

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: add .dockerignore to keep build context lean and block secrets"
```

---

## Task 4: Rewrite `Dockerfile`

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Replace `Dockerfile` contents**

Replace the entire contents of `/mnt/c/Users/sonit/Github/Fivos_Senior_Project/Dockerfile` with:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install only Chromium (scraper uses chromium.launch() exclusively)
# Firefox + WebKit would add ~500MB with no functional benefit.
RUN playwright install chromium

COPY . .

EXPOSE 8000

CMD ["python", "run.py"]
```

Note the ordering: `requirements.txt` is copied and installed **before** copying the rest of the repo. This lets Docker cache the pip install layer so code-only changes don't trigger a full reinstall.

- [ ] **Step 2: Build the image**

Run: `docker build -t fivos-app:test .`

Expected: builds successfully. The first build will download the ~1.5GB Playwright base image and ~200MB of Python deps. Subsequent builds with only code changes should skip both.

If the build fails on a specific pip package, note the package and check `requirements.txt` — the Playwright base image has the same Python version (3.11) as `python:3.11-slim`, so any issue would be a Linux package missing. Most common cause: a package that needs `gcc` or `build-essential`. If that happens, add this BEFORE the `pip install` line:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 3: Smoke-test the image in isolation (without compose)**

Run:
```bash
docker run --rm fivos-app:test python -c "from playwright.async_api import async_playwright; print('playwright ok')"
```

Expected: prints `playwright ok`.

Run:
```bash
docker run --rm fivos-app:test python -c "from app.main import app; print('fastapi ok')"
```

Expected: prints `fastapi ok` (may also print the "Seeding demo users" lifespan log). If it errors about Mongo, that's fine — just means the app module imported successfully; we'll wire up Mongo in Task 5.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): rebuild Dockerfile on Playwright base image

Use mcr.microsoft.com/playwright/python:v1.47.0-jammy as base so
Chromium, its system deps, and Python 3.11 are already present. Only
install Chromium (not Firefox/WebKit) since scraper.py uses chromium
exclusively. Order COPY so pip install layer caches across code edits."
```

---

## Task 5: Rewrite `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace `docker-compose.yml` contents**

Replace the entire contents of `/mnt/c/Users/sonit/Github/Fivos_Senior_Project/docker-compose.yml` with:

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - FIVOS_MONGO_URI=mongodb://mongo:27017/fivos
      - OLLAMA_URL=http://ollama:11434/api/chat
    volumes:
      - harvester_output:/app/harvester/output
      - harvester_logs:/app/harvester/log-files
      - scraper_html:/app/web-scraper/out_html
    depends_on:
      mongo:
        condition: service_healthy
      ollama:
        condition: service_started

  mongo:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  ollama-init:
    image: ollama/ollama:latest
    depends_on:
      ollama:
        condition: service_started
    volumes:
      - ollama_models:/root/.ollama
    environment:
      - OLLAMA_HOST=http://ollama:11434
    entrypoint: >
      sh -c "
        sleep 5 &&
        ollama pull gemma4:latest &&
        ollama pull qwen2.5:7b &&
        ollama pull mistral &&
        echo 'All models ready'
      "
    restart: "no"

volumes:
  mongo_data:
  ollama_models:
  harvester_output:
  harvester_logs:
  scraper_html:
```

- [ ] **Step 2: Validate compose syntax**

Run: `docker compose config`

Expected: prints the fully-resolved compose config with no errors. If it errors about `.env` missing, copy from `.env.example`:

```bash
cp .env.example .env
# Edit .env to set real FIVOS_MONGO_URI, GROQ_API_KEY, NVIDIA_API_KEY, AUTH_SECRET_KEY
```

Note: `FIVOS_MONGO_URI` in `.env` doesn't matter — compose overrides it to `mongodb://mongo:27017/fivos`. But `.env` must still exist (compose errors if `env_file` target is missing).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add mongo healthcheck, ollama GPU service, init sidecar

- mongo: healthcheck via mongosh ping, app waits for service_healthy
- ollama: GPU passthrough via nvidia runtime
- ollama-init: one-shot sidecar that pulls gemma4:latest, qwen2.5:7b,
  mistral into ollama_models volume; no-op on subsequent runs
- app: FIVOS_MONGO_URI and OLLAMA_URL overridden for container networking
- volumes for harvester output/logs and scraped HTML persistence"
```

---

## Task 6: NVIDIA Container Toolkit verification

This task does not modify files — it verifies the host is ready for GPU passthrough. Skip implementation if already installed.

- [ ] **Step 1: Check if NVIDIA Container Toolkit is installed**

Run: `docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`

Expected outcomes:
- **Success:** prints the `nvidia-smi` table showing the RTX 4070. Proceed to Task 7.
- **Failure with "unknown flag: --gpus"**: Docker version too old. Install Docker Engine 19.03+.
- **Failure with "could not select device driver"**: NVIDIA Container Toolkit not installed. Continue to Step 2.

- [ ] **Step 2: Install NVIDIA Container Toolkit (Ubuntu / WSL2 only, skip if Step 1 succeeded)**

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

- [ ] **Step 3: Re-verify**

Run: `docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`

Expected: prints the GPU info table.

No commit — this is a host configuration step, not a source change.

---

## Task 7: End-to-end smoke test (first run)

This task verifies the full stack boots from a cold start and downloads the Ollama models.

- [ ] **Step 1: Clean any prior state**

```bash
docker compose down -v
```

The `-v` flag wipes named volumes. This ensures we test the true cold-start path including model download.

- [ ] **Step 2: Start the stack**

Run: `docker compose up`

Expected sequence in the logs (interleaved across services):
1. `mongo-1` starts, healthcheck eventually passes (~15s).
2. `ollama-1` starts, logs "Listening on [::]:11434".
3. `ollama-init-1` starts, sleeps 5s, then logs `pulling gemma4:latest` (progress %), then `pulling qwen2.5:7b`, then `pulling mistral`, then `All models ready`, then exits with code 0.
4. `app-1` waits for mongo healthy, then starts. Logs `Server running at http://localhost:8000`.

**Expected first-run duration:** 15-25 minutes, dominated by the ~17 GB model download. Progress bars should be visible in `ollama-init-1` logs.

- [ ] **Step 3: Verify HTTP response**

In a second terminal:

```bash
curl -sI http://localhost:8000/auth/login
```

Expected: `HTTP/1.1 200 OK` with `content-type: text/html`.

- [ ] **Step 4: Verify Ollama from inside the app container**

```bash
docker compose exec app python -c "
import os
print('OLLAMA_URL:', os.getenv('OLLAMA_URL'))
import requests
r = requests.get(os.getenv('OLLAMA_URL').replace('/api/chat', '/api/tags'))
print('models:', [m['name'] for m in r.json().get('models', [])])
"
```

Expected output:
```
OLLAMA_URL: http://ollama:11434/api/chat
models: ['gemma4:latest', 'qwen2.5:7b', 'mistral:latest']
```

(Exact tag suffixes may vary — `mistral` may come back as `mistral:latest`. The important thing is all three are present.)

- [ ] **Step 5: Verify Mongo from inside the app container**

```bash
docker compose exec app python -c "
from harvester.src.database.db_connection import get_db
db = get_db()
print('collections:', db.list_collection_names())
print('mongo ok')
"
```

Expected: prints something like `collections: ['users']` (users collection is seeded by the FastAPI lifespan on startup) and `mongo ok`.

- [ ] **Step 6: End-to-end harvest test via the web UI**

In a browser, go to `http://localhost:8000/auth/login`. Log in as the seeded admin (`admin@fivos.local` / `admin123` — you'll be forced to change the password on first login per the 2026-04-04 auth work).

Navigate to `/harvester`. Submit a single test URL (any manufacturer product page). Watch the progress. Expected result: at least one device inserted into the `devices` collection.

Verify in another terminal:

```bash
docker compose exec app python -c "
from harvester.src.database.db_connection import get_db
db = get_db()
print('device count:', db.devices.count_documents({}))
"
```

Expected: `device count: >= 1`.

- [ ] **Step 7: Shut down cleanly**

In the `docker compose up` terminal, press Ctrl-C. Then:

```bash
docker compose down
```

(No `-v` — we want to keep the volumes for the next task.)

No commit — this is verification only.

---

## Task 8: Warm-start smoke test

Verify second-run performance: models should already be cached, startup should be fast.

- [ ] **Step 1: Cold restart (volumes intact)**

Run: `docker compose up`

Expected: `ollama-init-1` runs `ollama pull gemma4:latest` etc. but each pull completes in <5 seconds with "already exists" or equivalent. `All models ready` logs within ~10 seconds. Total time from `docker compose up` to `Server running at http://localhost:8000`: under 30 seconds.

- [ ] **Step 2: Verify app still responds**

```bash
curl -sI http://localhost:8000/auth/login
```

Expected: `HTTP/1.1 200 OK`.

- [ ] **Step 3: Verify MongoDB data persisted**

```bash
docker compose exec app python -c "
from harvester.src.database.db_connection import get_db
print('device count:', get_db().devices.count_documents({}))
"
```

Expected: same device count as at the end of Task 7, Step 6 (data in `mongo_data` volume survived the restart).

- [ ] **Step 4: Shut down**

Ctrl-C, then `docker compose down`.

No commit — this is verification only.

---

## Task 9: Update `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Locate the Install section**

Run:

```bash
grep -n "^##" README.md
```

Find the heading for the install/quick-start section (likely `## Install` or `## Quick Start`).

- [ ] **Step 2: Add the Docker Setup section**

Insert this section **immediately after** the existing install section in `README.md`:

````markdown
## Docker Setup (Recommended for Handoff)

Run the entire stack — FastAPI app, MongoDB, and GPU-accelerated Ollama with all three models — with one command.

### Prerequisites

1. **Docker Engine 19.03+** with Docker Compose v2
2. **NVIDIA GPU** (tested on RTX 4070) + NVIDIA drivers installed on the host
3. **NVIDIA Container Toolkit** — required for GPU passthrough:

   ```bash
   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
     sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

   Verify: `docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`

### First-Time Setup

```bash
cp .env.example .env
# Edit .env: set GROQ_API_KEY, NVIDIA_API_KEY, AUTH_SECRET_KEY
# FIVOS_MONGO_URI in .env is ignored — compose overrides to mongodb://mongo:27017/fivos
docker compose up
```

**First run takes 15-25 minutes** — the `ollama-init` sidecar downloads three models totaling ~17 GB (`gemma4:latest`, `qwen2.5:7b`, `mistral`). Watch the `ollama-init-1` logs for progress. Models are saved to a named volume, so subsequent runs take under 30 seconds.

When you see `Server running at http://localhost:8000` in the `app-1` logs, open the dashboard in your browser.

### Common Commands

| Command | Purpose |
|---|---|
| `docker compose up` | Start everything (foreground) |
| `docker compose up -d` | Start in background |
| `docker compose logs -f app` | Tail the FastAPI logs |
| `docker compose logs -f ollama-init` | Watch the model download on first run |
| `docker compose down` | Stop everything (keeps volumes) |
| `docker compose down -v` | Stop and wipe all volumes (re-downloads models on next up) |
| `docker compose exec app bash` | Shell into the app container |
| `docker compose build --no-cache` | Force full rebuild of the app image |

### Architecture

- **`app`** — FastAPI dashboard + harvester pipeline, port 8000
- **`mongo`** — MongoDB 7, port 27017, persisted to `mongo_data` volume
- **`ollama`** — Ollama server with GPU passthrough, port 11434, models in `ollama_models` volume
- **`ollama-init`** — one-shot container that pulls the three required models on first run

### Troubleshooting

**`docker compose up` fails with "could not select device driver ... nvidia"**
→ NVIDIA Container Toolkit not installed. See Prerequisites above.

**`ollama-init` hangs or errors during `ollama pull`**
→ Check internet connectivity and disk space (need ~20 GB free for models). Re-run `docker compose up ollama-init` to resume the download.

**`app` crashes with "connection refused" to mongo**
→ Mongo healthcheck hasn't passed yet. The `depends_on: condition: service_healthy` should prevent this; if it persists, check `docker compose logs mongo` for errors.

**Port conflict on 8000 / 27017 / 11434**
→ Something on the host is already using that port. Either stop the conflicting process or edit the `ports:` mappings in `docker-compose.yml`.
````

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): add Docker Setup section with prerequisites and troubleshooting"
```

---

## Task 10: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Commands section**

In `/mnt/c/Users/sonit/Github/Fivos_Senior_Project/CLAUDE.md`, find the existing `## Commands` section (starts around line 18 with `pip install -r requirements.txt && playwright install`).

**Add** a new Docker subsection directly after the existing commands block. Find this block:

```markdown
```bash
pip install -r requirements.txt && playwright install   # Install
pytest                                                   # All tests
python harvester/src/pipeline/cli.py                     # Interactive CLI menu
uvicorn app.main:app --port 8000                         # Web dashboard
```
```

**Immediately after** that closing ``` ` ``` backticks block, insert:

````markdown
### Docker (full stack)

```bash
docker compose up                    # Start app + mongo + ollama + model download
docker compose up -d                 # Same, detached
docker compose down                  # Stop (keeps volumes)
docker compose down -v               # Stop + wipe volumes (forces model re-download)
docker compose logs -f app           # Tail FastAPI logs
docker compose exec app bash         # Shell into app container
```

First run downloads ~17GB of Ollama models (`gemma4:latest`, `qwen2.5:7b`, `mistral`) into the `ollama_models` named volume via the `ollama-init` sidecar. Subsequent runs are instant. Requires NVIDIA Container Toolkit on the host — see `README.md` Docker Setup section.
````

- [ ] **Step 2: Update the Environment section**

Find this existing line in `CLAUDE.md`:

```markdown
Copy `.env.example` → `.env`. Required: `FIVOS_MONGO_URI`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `AUTH_SECRET_KEY`.
```

**Replace** it with:

```markdown
Copy `.env.example` → `.env`. Required: `FIVOS_MONGO_URI`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `AUTH_SECRET_KEY`. Optional: `OLLAMA_URL` (defaults to `http://localhost:11434/api/chat`; compose overrides to `http://ollama:11434/api/chat`), `UVICORN_RELOAD` (default `false`; set `true` for local dev auto-reload).

In Docker, compose overrides `FIVOS_MONGO_URI` → `mongodb://mongo:27017/fivos` and `OLLAMA_URL` → `http://ollama:11434/api/chat`. The rest of `.env` is injected via `env_file`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document Docker commands and OLLAMA_URL/UVICORN_RELOAD env vars"
```

---

## Task 11: Final verification and branch cleanup

- [ ] **Step 1: Full test suite**

Run: `pytest -q`

Expected: all tests pass. The only new tests are from Task 1 (`test_llm_extractor_env.py`), everything else is baseline + 2 new tests.

- [ ] **Step 2: Full cold-start round-trip**

```bash
docker compose down -v
docker compose up
```

Wait for `Server running at http://localhost:8000`. Then Ctrl-C and:

```bash
docker compose down
```

Expected: all four services start cleanly, models download, app responds, shutdown is clean.

- [ ] **Step 3: Review git log**

Run: `git log --oneline main..HEAD`

Expected: ~8 commits covering all the changes above, each with a focused message.

- [ ] **Step 4: Invoke `finishing-a-development-branch` skill**

Use the `superpowers:finishing-a-development-branch` skill to decide how to merge this into the main branch (PR vs direct merge vs further review).

---

## Spec Coverage Check

Verifying the plan covers every item in the spec:

| Spec section | Plan task |
|---|---|
| 3 services + ollama-init sidecar | Task 5 |
| Named volumes (5 total) | Task 5 |
| Playwright base image + Chromium only | Task 4 |
| `OLLAMA_URL` env var | Task 1 |
| `UVICORN_RELOAD` env var | Task 2 |
| `.dockerignore` | Task 3 |
| GPU passthrough via NVIDIA runtime | Task 5 + Task 6 (host setup) |
| Mongo healthcheck + depends_on service_healthy | Task 5 |
| Auto-pull `gemma4:latest`, `qwen2.5:7b`, `mistral` | Task 5 |
| Compose-level env override for `FIVOS_MONGO_URI` and `OLLAMA_URL` | Task 5 |
| README Docker Setup section with NVIDIA Container Toolkit install | Task 9 |
| CLAUDE.md Docker commands + env vars | Task 10 |
| Verification steps 1-6 from spec | Tasks 7 + 8 + 11 |

All spec items covered.
