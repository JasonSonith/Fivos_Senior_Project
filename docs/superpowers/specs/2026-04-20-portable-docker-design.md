# Portable Docker — Client Install Design Spec

**Date:** 2026-04-20
**Author:** Jason Sonith
**Status:** Approved (pending implementation)

## Goal

Make `docker compose up` succeed on any laptop with Docker installed (Mac Apple Silicon, Windows Docker Desktop, Linux — with or without an NVIDIA GPU). Target audience: the client (Doug Greene, Fivos Health) for demo / evaluation. No manual Python, Playwright, Ollama, or GPU toolkit installs required.

## Non-Goals

- One-click installer (`.dmg` / `.exe` / `.pkg`). Client installs Docker Desktop themselves.
- HTTPS / TLS termination. Client runs on `localhost:8000` for evaluation.
- Corporate proxy or air-gapped network handling. Separate conversation if it comes up.
- Replacement of the existing developer / CLI / local-venv workflow. That path stays available, just demoted to a subsection.

## Design Decisions

### 1. Cloud-first LLM chain, small local model as emergency fallback

Reorder `MODEL_CHAIN` in `harvester/src/pipeline/llm_extractor.py` to:

1. Groq `llama-3.3-70b-versatile`
2. Groq `llama-3.1-8b-instant`
3. NVIDIA `meta/llama-3.3-70b-instruct`
4. NVIDIA `mistralai/mistral-large`
5. NVIDIA `google/gemma-2-27b-it`
6. Ollama `qwen2.5:3b` — only local model

Rationale: on a no-GPU laptop, gemma4 (9.6GB) is unusable on CPU (minutes per page). Cloud providers are fast even on a laptop and both offer generous free tiers. `qwen2.5:3b` (~2GB) covers the "cloud is unreachable" case with usable (if slow) extraction.

### 2. Thread and concurrency architecture unchanged

`ThreadPoolExecutor(max_workers=4)`, per-provider semaphores (`OLLAMA=1`, `GROQ=3`, `NVIDIA=4`), non-blocking `sem.acquire` fall-through, `threading.local()` `_last_model_used`, and locked `_disabled_models` all stay exactly as implemented in the 2026-04-08 parallelization work. Only the chain ordering changes.

Under the new ordering, 4 parallel workers comfortably fit inside the cloud pools (Groq=3 + NVIDIA=4 = 7 slots), so the local model is rarely touched.

### 3. API keys delivered out of band

`.env.example` stays committed with blank `GROQ_API_KEY=` and `NVIDIA_API_KEY=`. A comment documents that the filled values arrive separately on handoff. Jason emails the client a complete `.env` file containing:

- `GROQ_API_KEY`
- `NVIDIA_API_KEY`
- `MONGO_PASSWORD`
- `AUTH_SECRET_KEY`

Keys never land in git. Jason retains control of the cloud accounts (revocable, monitorable).

### 4. Compose file split — CPU-only default, GPU opt-in override

`docker-compose.yml` becomes the portable default:

- `ollama` service: **remove** the `deploy.resources.reservations.devices` NVIDIA block entirely. Ollama runs CPU-only.
- `ollama-init` sidecar: pulls only `qwen2.5:3b` (entrypoint `sh -c "sleep 5 && ollama pull qwen2.5:3b && echo 'Model ready'"`).
- `app` and `mongo` services unchanged.

New file `docker-compose.gpu.yml` — thin override for Jason's dev box or a GPU-equipped teammate:

```yaml
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

Usage: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up`. Documented in the README's "For Developers" subsection.

### 5. Sample URLs file for first-run demo

Ship `sample_urls.txt` at repo root with ~5 manufacturer URLs covering at least 3 different brands (drawn from existing `harvester/src/urls.txt`). README tells the client to paste it into the batch-upload tab on `/harvester`. First-run flow:

1. `docker compose up`
2. Open `http://localhost:8000`, log in as `admin@fivos.local` / `admin123`, set a new password
3. Open `/harvester`, upload `sample_urls.txt`
4. Wait ~2 minutes
5. Dashboard populates; discrepancy queue has entries; review page works

Empty-by-default DB is preferred over pre-seeded fake data — client sees the real pipeline run.

### 6. README rewrite

Sections to remove as obsolete:

| Existing section | Reason |
|---|---|
| "Prerequisites" local Python list (refs gemma4 / qwen2.5:7b / mistral) | Wrong models; client path is Docker |
| Local "Installation" (`git clone` / `venv` / `pip install`) | Not the client path |
| NVIDIA Prerequisites + toolkit install commands | No GPU required |
| First-Time Setup claiming 17GB download / 15-25 min first run | Now ~2GB / ~5-10 min |
| Six-step Handoff Verification (GPU check, 3-model check) | Assumptions don't match new compose |
| WSL NVIDIA troubleshooting items | Can't hit without NVIDIA block in compose |

Sections to keep and update:

- Architecture mermaid diagram — change `gemma4 → Groq → NVIDIA` chain label to `Groq → NVIDIA → qwen2.5:3b (emergency)`.
- "Common Commands" table — stays.
- "Architecture" service list — drop "GPU passthrough" from ollama; change "three required models" to "one small local model as offline fallback".
- "Environment Variables" — stays.
- "Troubleshooting" — drop NVIDIA items, keep port-conflict + mongo items, add "corporate firewall blocks Docker Hub" pointer.
- "Key Features" — update chain description from 8-model to 6-model; drop "GPU-accelerated" if used anywhere.

New "Getting Started (Client Install)" section, added near the top, replaces the removed blocks. Six numbered steps (install Docker → drop .env → `docker compose up` → browser → login → upload sample_urls.txt). Prereq list: Docker Desktop + 8GB disk + internet for first run.

Existing local-venv / Uvicorn / CLI workflow preserved under a smaller "For Developers" subsection at the bottom of Getting Started. Covers: `pip install`, `playwright install`, `uvicorn app.main:app`, `python harvester/src/pipeline/cli.py`, GPU override compose command.

## Files Touched

| File | Action |
|---|---|
| `docker-compose.yml` | Remove NVIDIA `deploy` block from `ollama`; change `ollama-init` entrypoint to pull `qwen2.5:3b` only |
| `docker-compose.gpu.yml` | **New** — GPU reservation override for dev use |
| `harvester/src/pipeline/llm_extractor.py` | Reorder `MODEL_CHAIN`: cloud first, `qwen2.5:3b` last; drop `gemma4`, `qwen2.5:7b`, `mistral` |
| `.env.example` | Comment noting keys delivered out of band |
| `sample_urls.txt` | **New** — repo root, ~5 manufacturer URLs |
| `README.md` | Remove obsolete handoff content; add Client Install section; update architecture labels and feature list |

## Platform Validation

Before shipping to the client, Jason verifies on at least one machine per platform (ideally):

- Linux/WSL2 (existing dev environment) — baseline
- Mac Apple Silicon (if available through a teammate or VM) — confirms ARM64 multi-arch Playwright base image works
- Windows with Docker Desktop (no NVIDIA) — confirms CPU-only Ollama boots

Acceptance for each platform: `docker compose up` → dashboard at `:8000` → upload `sample_urls.txt` → dashboard populates.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Client's corporate network blocks Docker Hub or Ollama CDN | README troubleshooting note; Jason available to help |
| Cloud providers both rate-limit during a live demo | `qwen2.5:3b` fallback kicks in; slow but works |
| Shared API keys burn quota unexpectedly | Jason monitors usage; keys are revocable |
| Apple Silicon Playwright issue (unlikely — base image is multi-arch) | Platform validation step catches it before handoff |
| Client needs their own keys long-term | `.env` is editable; swap is trivial, README flags it |

## Out of Scope (future work if needed)

- Auto-update / pull-latest flow for the client
- Offline air-gapped install (would require baking models into the image and shipping via USB)
- Production deployment (cloud VM, TLS, persistent backups, monitoring)
- One-click installer
