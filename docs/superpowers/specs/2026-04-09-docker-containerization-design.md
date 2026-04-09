# Docker Containerization — Design Spec

**Date:** 2026-04-09
**Author:** Jason
**Status:** Approved (pending user spec review)

---

## Problem

The project was partially dockerized in recent commits (`Dockerfile`, `docker-compose.yml`) but the containerization is incomplete:

- `Dockerfile` uses `python:3.11-slim` and does not install Playwright browser binaries or their system dependencies, so the scraper cannot run inside the container.
- `docker-compose.yml` only defines `app` + `mongo`. There is no Ollama service — the app container cannot reach the host's Ollama at `localhost:11434` because `localhost` inside a container means the container itself.
- Ollama model pulls (`gemma4:latest`, `qwen2.5:7b`, `mistral`) are not automated.
- `FIVOS_MONGO_URI` and `OLLAMA_URL` hardcode or default to `localhost`, which breaks in a container network.
- No `.dockerignore`, so every build ships `.git`, log files, scraped HTML, and potentially `.env` into the build context.
- `run.py` uses `reload=True`, which is a dev-only flag that causes repeated restarts in a containerized production run.

The system will be handed off to Fivos, who run a similar PC build (NVIDIA GPU, Linux/WSL2). Handoff should be a clone + `docker compose up` — no manual Ollama install, no manual model pulls, no per-machine Python setup.

## Goals

1. Fresh clone + `docker compose up` starts the entire stack: FastAPI, MongoDB, Ollama with GPU, and all three required Ollama models downloaded on first run.
2. Playwright-based scraping works inside the container.
3. Secrets stay in `.env` (not committed). Container-specific overrides (Mongo URI, Ollama URL) live in `docker-compose.yml`, not `.env`, so local non-Docker dev continues to work unchanged.
4. First run downloads ~17 GB of Ollama models once; subsequent runs are instant via a named volume.
5. Fallback chain behavior inside the container matches the documented 8-model chain in `CLAUDE.md`.
6. Non-Docker local dev (running `python harvester/src/pipeline/runner.py` directly, or `uvicorn app.main:app`) continues to work with zero changes.

## Non-Goals

- Multi-host orchestration (Kubernetes, Swarm). Single-host Docker Compose only.
- CI/CD pipeline changes. Out of scope for this spec.
- Rewriting the pipeline to be async or containers-native. Code changes are minimal.
- Publishing images to a registry. Fivos builds locally from source.
- Supporting CPU-only Ollama. Gemma4 on CPU is unusably slow; GPU is required.

## Architecture

Three services on a single Docker Compose network:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│     app      │────▶│    mongo     │     │    ollama    │
│  FastAPI +   │     │  mongo:7     │     │   +GPU       │
│  harvester   │     │  port 27017  │     │  port 11434  │
│  port 8000   │     └──────────────┘     └──────────────┘
└──────┬───────┘            ▲                     ▲
       │                    │                     │
       └────────────────────┴─────────────────────┘
                   compose default network

       ┌──────────────────┐
       │   ollama-init    │  runs once, pulls 3 models into
       │   (sidecar)      │  ollama_models volume, then exits
       └──────────────────┘
```

### Services

**`app`** — FastAPI web UI + harvester pipeline. Built from local `Dockerfile`. Exposes port 8000. Depends on `mongo` (healthy) and `ollama` (started). Reads secrets from `.env` via `env_file`; compose overrides `FIVOS_MONGO_URI` and `OLLAMA_URL` via `environment`.

**`mongo`** — Unchanged from current `docker-compose.yml` except for an added healthcheck. Persists to `mongo_data` volume.

**`ollama`** — Official `ollama/ollama:latest` image. GPU passthrough via `deploy.resources.reservations.devices` (requires NVIDIA Container Toolkit on the host). Persists models to `ollama_models` volume.

**`ollama-init`** — Sidecar using the same `ollama/ollama:latest` image. `entrypoint` runs `ollama pull` for each model against the `ollama` service, then exits. `restart: "no"`. On subsequent `docker compose up`, pulls are no-ops (already-cached models return immediately).

### Volumes

| Volume | Mount | Purpose |
|---|---|---|
| `mongo_data` | `mongo:/data/db` | MongoDB persistence (already exists) |
| `ollama_models` | `ollama:/root/.ollama` | Downloaded model blobs (~17 GB) |
| `harvester_output` | `app:/app/harvester/output` | JSON extraction output |
| `harvester_logs` | `app:/app/harvester/log-files` | Pipeline log files |
| `scraper_html` | `app:/app/web-scraper/out_html` | Raw scraped HTML cache |

Bind-mounting the three `app` data directories to named volumes (rather than host paths) keeps the setup portable across Linux/Mac/WSL2 without path-munging. Host-side access is via `docker compose cp` or `docker volume inspect` if needed.

## Dockerfile Design

**Base image:** `mcr.microsoft.com/playwright/python:v1.47.0-jammy`

Rationale: Microsoft's official Playwright Python image includes Chromium, Firefox, WebKit, and all system dependencies (libnss, libatk, fonts, etc.) pre-installed. Using it avoids a brittle apt-install list and keeps the Dockerfile small. It ships with Python 3.11. Project `CLAUDE.md` lists Python 3.13.7 for local dev, but a grep of the codebase shows no 3.13-specific syntax (no PEP 695 `type` aliases, no PEP 701 f-string features). 3.11 is safe.

**Steps:**
1. `FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy`
2. `WORKDIR /app`
3. `COPY requirements.txt .`
4. `RUN pip install --no-cache-dir -r requirements.txt`
5. `RUN playwright install chromium` — only Chromium (the scraper does not use Firefox/WebKit), saves ~500 MB
6. `COPY . .`
7. `EXPOSE 8000`
8. `CMD ["python", "run.py"]`

## Code Changes

Two minimal source changes required. Both preserve local non-Docker dev behavior via env-var defaults.

### 1. `harvester/src/pipeline/llm_extractor.py:17`

**Before:**
```python
OLLAMA_URL = "http://localhost:11434/api/chat"
```

**After:**
```python
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
```

Compose sets `OLLAMA_URL=http://ollama:11434/api/chat` on the `app` service. Local dev picks up the default.

### 2. `run.py`

**Before:**
```python
uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
```

**After:**
```python
import os
reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=reload)
```

Compose does not set `UVICORN_RELOAD`, so the container runs stable. Local dev can export `UVICORN_RELOAD=true` if desired.

## docker-compose.yml Design

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

## `.dockerignore`

New file at repo root. Excludes:

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

Keeps build context small, prevents shipping secrets (`.env`) or development junk into the image.

## Host Setup (one-time, documented in README)

Fivos needs NVIDIA Container Toolkit installed on their host machine before `docker compose up` will work with GPU passthrough:

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

Verify with: `docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi`

## Documentation Updates

- **`README.md`** — new "Docker Setup" section covering: prerequisites (Docker, NVIDIA Container Toolkit), `.env` setup, first-run expectations (~15 min model download), `docker compose up`, common commands (`docker compose logs -f app`, `docker compose down`, `docker compose down -v` to wipe volumes).
- **`CLAUDE.md`** — add Docker commands section alongside existing pip install / pytest / runner commands. Document the `OLLAMA_URL` env var and the `FIVOS_MONGO_URI` compose override.

## Error Handling & Edge Cases

| Scenario | Behavior |
|---|---|
| NVIDIA Container Toolkit missing | `docker compose up` fails with a clear nvidia runtime error. README documents the fix. |
| First-run model download interrupted | `ollama pull` is resumable; re-running `docker compose up` resumes the download. |
| `.env` missing `GROQ_API_KEY` / `NVIDIA_API_KEY` | App starts; LLM fallback chain skips those providers (existing behavior). |
| `.env` missing entirely | Compose errors on `env_file: .env not found`. README documents `cp .env.example .env`. |
| Mongo not healthy when app starts | `depends_on: condition: service_healthy` blocks app startup until Mongo responds to ping. |
| Ollama slow to start when init runs | Init script has `sleep 5` as a cushion. If pulls fail, init container exits nonzero; user re-runs `docker compose up ollama-init`. |
| Ollama GPU OOM | Same failure mode as non-Docker: gemma4 fails, chain falls through to Groq/NVIDIA/smaller models. |
| Ports 8000 / 27017 / 11434 already in use on host | Compose errors with a clear port-conflict message. User edits `docker-compose.yml` port mappings. |

## Testing / Verification

After implementation, verify in order:

1. `docker compose build` — Dockerfile builds clean, no apt/pip errors.
2. `docker compose up` — all 4 services start; `ollama-init` completes with "All models ready"; `app` log shows "Server running at http://localhost:8000".
3. `curl http://localhost:8000/auth/login` — returns HTML login page (confirms FastAPI up).
4. Log in via browser → `/harvester` → submit a test URL → confirm scrape + extract + DB write end-to-end. Check log output for `[MainThread]` and `[extract_0..3]` thread names.
5. `docker compose down && docker compose up` — second run: `ollama-init` completes in <5 seconds (no re-download). Total startup <30 seconds.
6. `docker compose down -v` then `docker compose up` — confirms full cold-start path still works.

## Files Touched

| File | Action |
|---|---|
| `Dockerfile` | Rewritten (Playwright base, Chromium install) |
| `docker-compose.yml` | Rewritten (4 services, volumes, healthcheck, GPU) |
| `.dockerignore` | **New** |
| `run.py` | Env-var-gated `reload` flag |
| `harvester/src/pipeline/llm_extractor.py` | Env-var-gated `OLLAMA_URL` |
| `README.md` | New Docker Setup section |
| `CLAUDE.md` | Docker commands + env vars documented |

## Open Questions

None. All design decisions resolved in brainstorming:
- Ollama in-container with GPU: **yes** (Option A)
- Models to preload: **all 3** (`gemma4:latest`, `qwen2.5:7b`, `mistral`)
- Base image: `mcr.microsoft.com/playwright/python:v1.47.0-jammy`
- Env override strategy: compose `environment:` block, not `.env` edits
