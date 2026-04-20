# Portable Docker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker compose up` succeed on any laptop (Mac Apple Silicon, Windows, Linux — no GPU required) so the client can run Fivos end-to-end without manual dependency installs.

**Architecture:** Cloud-first LLM chain (Groq → NVIDIA) with one small local model (`qwen2.5:3b`) as emergency fallback. GPU support preserved as an opt-in compose override (`docker-compose.gpu.yml`). All threading / semaphore logic unchanged.

**Tech Stack:** Docker Compose, Ollama, Groq API, NVIDIA NIM API, FastAPI, MongoDB, pytest.

**Spec:** `docs/superpowers/specs/2026-04-20-portable-docker-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `harvester/src/pipeline/llm_extractor.py` | Modify | Reorder `MODEL_CHAIN` — drop 3 locals, keep 1 small local, cloud first |
| `harvester/src/pipeline/tests/test_llm_extractor_env.py` | Modify | Add chain-order test |
| `docker-compose.yml` | Modify | Remove NVIDIA `deploy` block; simplify `ollama-init` to pull one model |
| `docker-compose.gpu.yml` | Create | GPU reservation override for dev use |
| `sample_urls.txt` | Create | 5 manufacturer URLs the client can paste into batch upload |
| `.env.example` | Modify | Annotate that filled keys are delivered out of band |
| `README.md` | Modify | Replace obsolete GPU-required handoff content with portable client install |

---

## Task 1: Reorder MODEL_CHAIN (TDD)

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py:19-28`
- Test: `harvester/src/pipeline/tests/test_llm_extractor_env.py`

- [ ] **Step 1: Write the failing test**

Append to `harvester/src/pipeline/tests/test_llm_extractor_env.py`:

```python
def test_model_chain_is_cloud_first_with_small_local_fallback():
    """Portable Docker: chain runs on any laptop without GPU."""
    import pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)

    chain = llm_extractor.MODEL_CHAIN
    assert len(chain) == 6, f"Expected 6 models, got {len(chain)}"

    # Cloud providers must come first
    assert chain[0] == {"provider": "groq", "model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY"}
    assert chain[1] == {"provider": "groq", "model": "llama-3.1-8b-instant", "env_key": "GROQ_API_KEY"}
    assert chain[2]["provider"] == "nvidia"
    assert chain[3]["provider"] == "nvidia"
    assert chain[4]["provider"] == "nvidia"

    # Single small local model as last resort
    assert chain[5] == {"provider": "ollama", "model": "qwen2.5:3b"}

    # Removed models must not appear
    model_names = [m["model"] for m in chain]
    assert "gemma4" not in model_names
    assert "qwen2.5:7b" not in model_names
    assert "mistral" not in model_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest harvester/src/pipeline/tests/test_llm_extractor_env.py::test_model_chain_is_cloud_first_with_small_local_fallback -v`

Expected: FAIL. First assertion that trips is `len(chain) == 6` (current chain has 8 entries).

- [ ] **Step 3: Replace MODEL_CHAIN in `llm_extractor.py`**

Replace lines 19-28 of `harvester/src/pipeline/llm_extractor.py` with:

```python
MODEL_CHAIN = [
    {"provider": "groq",   "model": "llama-3.3-70b-versatile",     "env_key": "GROQ_API_KEY"},
    {"provider": "groq",   "model": "llama-3.1-8b-instant",        "env_key": "GROQ_API_KEY"},
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "env_key": "NVIDIA_API_KEY"},
    {"provider": "nvidia", "model": "mistralai/mistral-large",     "env_key": "NVIDIA_API_KEY"},
    {"provider": "nvidia", "model": "google/gemma-2-27b-it",       "env_key": "NVIDIA_API_KEY"},
    {"provider": "ollama", "model": "qwen2.5:3b"},
]
```

Also update the comment on line 30-32 to match the new context:

```python
# Concurrency knobs — tuned for cloud-first chain + single small local fallback.
# Groq/NVIDIA caps match free-tier rate limits; Ollama stays at 1 for CPU hosts.
# See docs/superpowers/specs/2026-04-08-llm-extractor-parallelization-design.md
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `pytest harvester/src/pipeline/tests/test_llm_extractor_env.py::test_model_chain_is_cloud_first_with_small_local_fallback -v`

Expected: PASS.

- [ ] **Step 5: Run the full pipeline test suite to catch regressions**

Run: `pytest harvester/src/pipeline/tests/ -v`

Expected: all existing tests still pass. Pay attention to `test_llm_extractor_concurrency.py` — the semaphore tests reference provider names (`ollama`, `groq`, `nvidia`), which are all still present in the new chain.

- [ ] **Step 6: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py harvester/src/pipeline/tests/test_llm_extractor_env.py
git commit -m "$(cat <<'EOF'
feat(llm): cloud-first MODEL_CHAIN with qwen2.5:3b local fallback

Reorder chain for no-GPU portability — drop gemma4, qwen2.5:7b, and
mistral (too large for CPU hosts); keep cloud providers in front and
one small local model as emergency fallback.

Threading and semaphore architecture unchanged.
EOF
)"
```

---

## Task 2: Update `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml:36-67`

- [ ] **Step 1: Remove the NVIDIA `deploy` block from the `ollama` service**

In `docker-compose.yml`, the current `ollama` service (lines 36-48) looks like:

```yaml
  ollama:
    image: ollama/ollama:latest
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Replace with:

```yaml
  ollama:
    image: ollama/ollama:latest
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - ollama_models:/root/.ollama
```

(The `deploy.resources.reservations.devices` block is removed entirely.)

- [ ] **Step 2: Simplify the `ollama-init` entrypoint to pull one model**

The current `ollama-init` service (lines 50-67) has an entrypoint pulling three models. Replace the `entrypoint` field with:

```yaml
    entrypoint: >
      sh -c "
        sleep 5 &&
        ollama pull qwen2.5:3b &&
        echo 'Model ready'
      "
```

Keep everything else about `ollama-init` (`depends_on`, `volumes`, `environment`, `restart`) unchanged.

- [ ] **Step 3: Verify compose syntax**

Run: `docker compose config > /dev/null`

Expected: no output, exit code 0. If compose complains, check indentation on the block you edited.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
feat(docker): remove GPU requirement; pull only qwen2.5:3b on init

Ollama now runs CPU-only by default so the stack boots on any laptop.
Model pull shrinks from ~17GB (gemma4 + qwen2.5:7b + mistral) to ~2GB.
GPU support lives in the new docker-compose.gpu.yml override.
EOF
)"
```

---

## Task 3: Create `docker-compose.gpu.yml` override

**Files:**
- Create: `docker-compose.gpu.yml`

- [ ] **Step 1: Create the override file at the repo root**

Write this exact content to `docker-compose.gpu.yml`:

```yaml
# GPU override — opt-in NVIDIA passthrough for Ollama.
# Usage: docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
#
# Requires NVIDIA Container Toolkit on the host:
#   https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

- [ ] **Step 2: Verify the override merges cleanly**

Run: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml config > /dev/null`

Expected: no output, exit code 0. If compose errors, check indentation.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.gpu.yml
git commit -m "$(cat <<'EOF'
feat(docker): add docker-compose.gpu.yml for opt-in GPU passthrough

Preserves the RTX / NVIDIA Container Toolkit workflow for local dev
without imposing it on the portable default.
EOF
)"
```

---

## Task 4: Create `sample_urls.txt`

**Files:**
- Create: `sample_urls.txt` (repo root)

- [ ] **Step 1: Create the file with 5 diverse manufacturer URLs**

Write this exact content to `sample_urls.txt`:

```
# Fivos demo sample — paste this file into the Batch Upload tab on /harvester.
# Five manufacturers, five device types. ~2 minutes to harvest end-to-end.

https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-drug-coated-balloons/inpact-admiral-drug-coated-balloon.html
https://www.goremedical.com/products/vbx/specifications
https://www.cookmedical.com/products/di_ziv_webds/
https://www.cardiovascular.abbott/us/en/hcp/products/peripheral-intervention/supera-stent-system/ordering.html
https://cordis.com/na/products/intervene/endovascular/self-expanding-stents/s-m-a-r-t-control-vascular-stent-system
```

- [ ] **Step 2: Commit**

```bash
git add sample_urls.txt
git commit -m "$(cat <<'EOF'
feat: add sample_urls.txt for first-run client demo

Five manufacturer URLs covering Medtronic, Gore, Cook, Abbott, and
Cordis — enough variety to exercise the extractor and validator end
to end in roughly two minutes.
EOF
)"
```

---

## Task 5: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add a note that filled keys are delivered out of band**

Replace lines 9-15 of `.env.example`:

```
# ── LLM APIs (fallback chain: Groq → NVIDIA → Ollama local) ─────────────────
# Get keys free:
#   Groq:   https://console.groq.com/keys
#   NVIDIA: https://build.nvidia.com → profile → API Keys → Generate
# If both are empty, falls back to local Ollama only.
GROQ_API_KEY=
NVIDIA_API_KEY=
```

with:

```
# ── LLM APIs (fallback chain: Groq → NVIDIA → local qwen2.5:3b) ─────────────
# For client install: Jason will email you a filled .env — paste it here.
# For devs / future swap: get your own free keys at
#   Groq:   https://console.groq.com/keys
#   NVIDIA: https://build.nvidia.com → profile → API Keys → Generate
# If both are empty, the system falls back to local Ollama only (slow on CPU).
GROQ_API_KEY=
NVIDIA_API_KEY=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "$(cat <<'EOF'
docs(env): note that handoff keys arrive out of band

Client install path: paste the .env Jason emails. Dev path: sign up
for free Groq + NVIDIA accounts. Keys never committed.
EOF
)"
```

---

## Task 6: Rewrite `README.md` for portable install

**Files:**
- Modify: `README.md`

This task has many steps because the README changes are large. Do them in order and commit once at the end.

- [ ] **Step 1: Update the mermaid architecture chain label**

In `README.md`, find the line in the mermaid block that reads:

```
    PARALLEL --> LLM[LLM Chain<br/>gemma4 → Groq → NVIDIA<br/>per-provider semaphores]
```

Replace with:

```
    PARALLEL --> LLM[LLM Chain<br/>Groq → NVIDIA → qwen2.5:3b fallback<br/>per-provider semaphores]
```

- [ ] **Step 2: Remove the obsolete "Prerequisites" and "Installation" blocks**

Delete lines 81-96 (everything from `## Getting Started` heading through the end of the local-venv install block). Do NOT delete the `## Getting Started` heading itself — it stays and becomes the parent of the new Client Install section added next.

After deletion, line 81 should be `## Getting Started` immediately followed by the `### Docker Setup (Recommended for Handoff)` heading (currently line 98).

- [ ] **Step 3: Replace the Docker Setup section AND the now-redundant Running the Dashboard section with a new Client Install block**

Find the heading `### Docker Setup (Recommended for Handoff)` and everything under it up to (but not including) `### Dashboard Pages`. That's roughly lines 98-252 of the current file — it absorbs the `### Running the Dashboard` subsection too, because its `uvicorn ... --reload` guidance is now covered by the For Developers subsection inside the replacement.

Keep the three sections that follow unchanged: `### Dashboard Pages`, `### Running the Pipeline (CLI)`, `### Running Tests`. Those are still useful references.

Replace the deleted range with:

````markdown
### Client Install (Docker)

Everything needed — Python, Playwright, Ollama, MongoDB, a small local LLM — comes with the Docker image. `docker compose up` boots the whole stack on any laptop (Mac, Windows, Linux) with no GPU required.

#### Prerequisites

1. **Docker Desktop** (Mac / Windows) or Docker Engine + Compose v2 (Linux).
   Install from https://www.docker.com/products/docker-desktop/.
2. **~8 GB free disk space** — image layers, MongoDB volume, one small local model.
3. **Internet for first run** — downloads the image + a ~2 GB local LLM.

#### Steps

1. Clone the repo (or unzip the bundle Jason sent) and `cd` into it.
2. Copy the `.env` file Jason emailed into the project root.
3. In a terminal in the project folder, run:
   ```bash
   docker compose up
   ```
   First run takes ~5–10 minutes (image build + local model pull). After that, starts in seconds.
4. Open http://localhost:8000 in your browser.
5. Log in with **admin@fivos.local / admin123** — you'll be forced to set a new password.
6. Open the **Harvester** page. In the **Batch Upload** tab, upload `sample_urls.txt` (included in the project root). Wait ~2 minutes.
7. The Dashboard now shows harvested devices and validation results. Click any "Partial Match" or "Mismatch" row to review discrepancies field-by-field.

#### Common Commands

| Command | Purpose |
|---|---|
| `docker compose up` | Start everything (foreground) |
| `docker compose up -d` | Start in background |
| `docker compose logs -f app` | Tail the FastAPI logs |
| `docker compose logs -f ollama-init` | Watch the model download on first run |
| `docker compose down` | Stop everything (keeps volumes and cached models) |
| `docker compose down -v` | Stop and wipe all volumes (re-downloads model next time) |
| `docker compose exec app bash` | Shell into the app container |
| `docker compose build --no-cache` | Force full rebuild of the app image |

#### Services

- **`app`** — FastAPI dashboard + harvester pipeline, port 8000
- **`mongo`** — MongoDB 7, localhost-only port 27017, persisted to `mongo_data` volume
- **`ollama`** — Ollama server (CPU), localhost-only port 11434, model in `ollama_models` volume
- **`ollama-init`** — one-shot container that pulls `qwen2.5:3b` (~2 GB) on first run

Cloud LLMs (Groq, NVIDIA NIM) handle extraction by default. The local `qwen2.5:3b` only runs when both cloud providers are unreachable.

#### Environment Variables

- `GROQ_API_KEY`, `NVIDIA_API_KEY` — cloud LLM keys. Delivered out of band by Jason for the client install.
- `MONGO_USERNAME`, `MONGO_PASSWORD` — database auth. `MONGO_PASSWORD` must be set; compose fails fast otherwise.
- `AUTH_SECRET_KEY` — FastAPI session cookie secret. Any 32+ character random string.
- `UVICORN_RELOAD` — set to the literal string `true` (case-insensitive) for dev auto-reload. Default `false`. `1`, `yes`, and `on` do NOT work.

#### Troubleshooting

**Port conflict on 8000 / 27017 / 11434** — something on the host already uses that port. Stop the conflicting process or edit the `ports:` mappings in `docker-compose.yml`.

**`app` crashes with "connection refused" to mongo** — the mongo healthcheck hasn't passed yet. `depends_on: condition: service_healthy` normally prevents this; if it persists, check `docker compose logs mongo`.

**`ollama-init` hangs on `ollama pull`** — the Ollama CDN is unreachable. Check internet connectivity. If you're on a corporate network that blocks Docker Hub or Ollama, ask your network admin to whitelist `registry.ollama.ai` and `hub.docker.com`.

**Extraction always fails with "all models disabled"** — both cloud keys are wrong/missing and the local fallback can't load. Check `docker compose logs app` for the specific error; confirm `GROQ_API_KEY` and `NVIDIA_API_KEY` in your `.env` are non-empty.

#### For Developers (optional GPU + local-venv workflow)

The stack above is CPU-only by default. If you have an NVIDIA GPU and the NVIDIA Container Toolkit installed, add the GPU override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

For non-Docker dev (local Python / hot-reload):

```bash
python3.13 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install
cp .env.example .env   # fill in FIVOS_MONGO_URI, GROQ_API_KEY, NVIDIA_API_KEY, AUTH_SECRET_KEY
uvicorn app.main:app --port 8000 --reload
# or run the CLI directly:
python harvester/src/pipeline/cli.py
```
````

- [ ] **Step 4: Update the "Key Features" section**

Find the "Key Features" section (currently around line 281). Replace the first bullet:

```
- LLM-powered extraction with 8-model fallback chain (gemma4 → Groq → NVIDIA → Ollama)
```

with:

```
- LLM-powered extraction with 6-model fallback chain (Groq → NVIDIA → local qwen2.5:3b fallback)
```

- [ ] **Step 5: Verify the mermaid diagram still renders**

Open `README.md` in a markdown preview (VS Code's preview works) and confirm the flow diagram renders without errors. If mermaid fails, revert only the mermaid chunk and re-apply Step 1 more carefully.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): portable client install replaces GPU-required handoff

Remove: NVIDIA Container Toolkit prereqs, 15-25 min first run claim,
17 GB three-model pull, six-step GPU verification, WSL-NVIDIA
troubleshooting. All obsolete under the cloud-first stack.

Add: Client Install section (Docker Desktop + 8 GB disk + .env paste),
sample_urls.txt walkthrough, GPU override pointer, For Developers
subsection preserving the local-venv workflow.
EOF
)"
```

---

## Task 7: End-to-end smoke test

**Files:** none modified (verification only)

- [ ] **Step 1: Wipe any existing volumes so the test is a true first run**

```bash
docker compose down -v
```

- [ ] **Step 2: Start the stack**

```bash
docker compose up
```

Expected timeline:
- Image pull / build: ~2–3 minutes
- `ollama-init` pulls qwen2.5:3b: ~2–5 minutes
- `app` starts: ~10 seconds after dependencies are healthy

- [ ] **Step 3: Verify dashboard is reachable**

In a new terminal:

```bash
curl -sI http://localhost:8000/auth/login
```

Expected: `HTTP/1.1 200 OK`.

- [ ] **Step 4: Verify the one Ollama model is present**

```bash
docker compose exec app python -c "
import os, requests
url = os.getenv('OLLAMA_URL', '').replace('/api/chat', '/api/tags')
print([m['name'] for m in requests.get(url).json().get('models', [])])
"
```

Expected: `['qwen2.5:3b']` (or similar with version suffix).

- [ ] **Step 5: Verify the GPU block is absent from the effective config**

```bash
docker compose config | grep -A5 'ollama:' | grep -A3 'deploy:' || echo 'no deploy block (expected)'
```

Expected: `no deploy block (expected)`.

- [ ] **Step 6: Run the sample harvest end to end (manual)**

Open http://localhost:8000/auth/login in a browser. Log in as `admin@fivos.local / admin123`. Set a new password when prompted. Navigate to `/harvester`, switch to Batch Upload, upload `sample_urls.txt`. Wait ~2 minutes. Confirm the Dashboard shows non-zero device + match counts.

- [ ] **Step 7: Verify devices were written to the DB**

```bash
docker compose exec app python -c "
from harvester.src.database.db_connection import get_db
db = get_db()
print('device count:', db.devices.count_documents({}))
print('validation count:', db.validationResults.count_documents({}))
"
```

Expected: `device count` is ≥ 5 (one SKU per URL minimum, many URLs produce multiple), `validation count` is ≥ 5.

- [ ] **Step 8: Optional — GPU override sanity check (only on a GPU host)**

If running on a machine with NVIDIA Container Toolkit, verify the override boots:

```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config | grep -A5 deploy
```

Expected: the `deploy.resources.reservations.devices` block with `driver: nvidia` is present in the merged config. Skip this step on non-GPU hosts.

- [ ] **Step 9: No commit**

Nothing to commit — this task is verification only. If any step failed, open an issue or revert the offending task.

---

## Self-Review Checklist

Before handing this plan off:

- [x] Every spec requirement has a task (compose split, chain reorder, sample urls, env comment, README rewrite)
- [x] No placeholders, TBDs, or "similar to above"
- [x] Every code-change step shows the actual code
- [x] Type consistency: `qwen2.5:3b` string identical in Tasks 1, 2, 6, and 7; `MODEL_CHAIN` structure matches existing file exactly
- [x] Commits are small and scoped (one per task)
- [x] Tests precede implementation where applicable (Task 1 TDD)
