# LLM Chain Swap — gemma4:e4b Primary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `qwen2.5:3b` with `gemma4:e4b` in the LLM fallback chain, promote it to primary, drop `nvidia google/gemma-2-27b-it`, reorder remaining cloud entries by capability, and update Docker + tests + docs to match.

**Architecture:** No code-logic changes. Pure data + config + docs swap. The `MODEL_CHAIN` list is iterated in order by `_llm_request`; semaphores key on provider name (unchanged). The Ollama init sidecar pulls the new model on first compose-up.

**Tech Stack:** Python 3.13, pytest, Docker Compose, Ollama.

**Spec:** `docs/superpowers/specs/2026-04-21-llm-chain-gemma4-swap-design.md`

---

## File Map

| File | Change |
|------|--------|
| `harvester/src/pipeline/tests/test_llm_extractor_env.py` | Rewrite chain test (Task 1) |
| `harvester/src/pipeline/llm_extractor.py` | New `MODEL_CHAIN` + concurrency comment (Task 2) |
| `docker/docker-compose.yml` | `ollama pull` model name (Task 3) |
| `.env.example` | Comment line referencing chain (Task 4) |
| `README.md` | 5 mentions + count + diagram label + line-131 rephrase (Task 4) |
| `CLAUDE.md` | Chain block + count + cloud-first sentence + first-run note (Task 4) |

---

### Task 1: Rewrite chain test (RED)

This task replaces the existing chain assertion test with one that matches the new chain. The test will FAIL after this task because `llm_extractor.py` still has the old chain — that's the intended TDD red state.

**Files:**
- Modify: `harvester/src/pipeline/tests/test_llm_extractor_env.py:19-41`

- [ ] **Step 1: Replace the chain test function**

Open `harvester/src/pipeline/tests/test_llm_extractor_env.py`. Replace lines 19-41 (the entire `test_model_chain_is_cloud_first_with_small_local_fallback` function) with:

```python
def test_model_chain_is_local_first_capability_ordered():
    """gemma4:e4b is primary; cloud models follow in capability order."""
    import pipeline.llm_extractor as llm_extractor
    importlib.reload(llm_extractor)

    chain = llm_extractor.MODEL_CHAIN
    assert len(chain) == 5, f"Expected 5 models, got {len(chain)}"

    # gemma4:e4b is primary (local, most capable per user judgment)
    assert chain[0] == {"provider": "ollama", "model": "gemma4:e4b"}

    # Cloud fallback ordered by raw capability
    assert chain[1] == {"provider": "nvidia", "model": "mistralai/mistral-large", "env_key": "NVIDIA_API_KEY"}
    assert chain[2] == {"provider": "groq", "model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY"}
    assert chain[3] == {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "env_key": "NVIDIA_API_KEY"}
    assert chain[4] == {"provider": "groq", "model": "llama-3.1-8b-instant", "env_key": "GROQ_API_KEY"}

    # Removed models must not appear
    model_names = [m["model"] for m in chain]
    assert "qwen2.5:3b" not in model_names
    assert "qwen2.5:7b" not in model_names
    assert "google/gemma-2-27b-it" not in model_names
```

The two other tests in the file (`test_ollama_url_defaults_to_localhost` at line 5, `test_ollama_url_respects_env_override` at line 12) MUST be left unchanged.

- [ ] **Step 2: Run the chain test to verify it fails (RED)**

Run from repo root:
```bash
cd harvester/src && python -m pytest pipeline/tests/test_llm_extractor_env.py::test_model_chain_is_local_first_capability_ordered -v
```

Expected: FAIL with an `AssertionError` on `len(chain) == 5` (current chain has 6 entries) or on `chain[0] == {"provider": "ollama", ...}` (current chain[0] is groq).

- [ ] **Step 3: Commit**

```bash
git add harvester/src/pipeline/tests/test_llm_extractor_env.py
git commit -m "test(llm-chain): assert local-first capability-ordered chain"
```

---

### Task 2: Update `MODEL_CHAIN` and concurrency comment (GREEN)

This task makes the new test pass by replacing the chain definition and updating the explanatory comment.

**Files:**
- Modify: `harvester/src/pipeline/llm_extractor.py:19-34`

- [ ] **Step 1: Replace the `MODEL_CHAIN` list**

In `harvester/src/pipeline/llm_extractor.py`, replace lines 19-26 (the current `MODEL_CHAIN = [...]` block) with:

```python
MODEL_CHAIN = [
    {"provider": "ollama", "model": "gemma4:e4b"},
    {"provider": "nvidia", "model": "mistralai/mistral-large",     "env_key": "NVIDIA_API_KEY"},
    {"provider": "groq",   "model": "llama-3.3-70b-versatile",     "env_key": "GROQ_API_KEY"},
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "env_key": "NVIDIA_API_KEY"},
    {"provider": "groq",   "model": "llama-3.1-8b-instant",        "env_key": "GROQ_API_KEY"},
]
```

- [ ] **Step 2: Replace the concurrency comment block**

Replace lines 28-34 (the comment block plus the four `*_WORKERS`/`*_CONCURRENCY` constants — but NOT the `_provider_sems` dict that follows) with:

```python
# Concurrency knobs — gemma4:e4b is primary (local-first, capability-ordered chain).
# OLLAMA_CONCURRENCY=1 keeps CPU hosts safe; cloud workers absorb overflow when
# the Ollama semaphore is saturated. Groq/NVIDIA caps match free-tier rate limits.
# See docs/superpowers/specs/2026-04-21-llm-chain-gemma4-swap-design.md
EXTRACT_WORKERS = 4
OLLAMA_CONCURRENCY = 1   # serialize on CPU-only hosts
GROQ_CONCURRENCY = 3     # ~30 RPM free tier
NVIDIA_CONCURRENCY = 4   # 40 RPM free tier
```

The `_provider_sems` dict on line 36 onwards stays untouched.

- [ ] **Step 3: Run the chain test to verify it passes (GREEN)**

```bash
cd harvester/src && python -m pytest pipeline/tests/test_llm_extractor_env.py -v
```

Expected: all 3 tests pass (`test_ollama_url_defaults_to_localhost`, `test_ollama_url_respects_env_override`, `test_model_chain_is_local_first_capability_ordered`).

- [ ] **Step 4: Commit**

```bash
git add harvester/src/pipeline/llm_extractor.py
git commit -m "feat(llm-chain): make gemma4:e4b primary, drop qwen and gemma-2-27b"
```

---

### Task 3: Update Docker `ollama-init` to pull gemma4:e4b

**Files:**
- Modify: `docker/docker-compose.yml:34-39`

- [ ] **Step 1: Replace the ollama-init entrypoint**

In `docker/docker-compose.yml`, find lines 34-39:

```yaml
    entrypoint: >
      sh -c "
        sleep 5 &&
        ollama pull qwen2.5:3b &&
        echo 'Model ready'
      "
```

Replace `ollama pull qwen2.5:3b` with `ollama pull gemma4:e4b`. Final result:

```yaml
    entrypoint: >
      sh -c "
        sleep 5 &&
        ollama pull gemma4:e4b &&
        echo 'Model ready'
      "
```

No other changes to `docker-compose.yml`.

- [ ] **Step 2: Verify the change**

```bash
grep -n 'ollama pull' docker/docker-compose.yml
```

Expected output: `        ollama pull gemma4:e4b &&`

- [ ] **Step 3: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "chore(docker): pull gemma4:e4b instead of qwen2.5:3b"
```

---

### Task 4: Update documentation

This task updates `.env.example`, `README.md`, and `CLAUDE.md` to match the new chain. Each file gets edits in order; verification grep at the end.

**Files:**
- Modify: `.env.example:12`
- Modify: `README.md:17,35,129,131,199`
- Modify: `CLAUDE.md:37,58,65-70,73,112`

- [ ] **Step 1: Update `.env.example` line 12**

Replace:
```
# ── LLM APIs (fallback chain: Groq → NVIDIA → local qwen2.5:3b) ─────────────
```
with:
```
# ── LLM APIs (fallback chain: local gemma4:e4b → NVIDIA → Groq) ─────────────
```

- [ ] **Step 2: Update `README.md` line 17**

Replace:
```
**The Harvester** crawls manufacturer websites using Playwright and extracts device specs using a 6-model LLM fallback chain (Groq → NVIDIA NIM → local qwen2.5:3b fallback). Extracted records are stored in MongoDB.
```
with:
```
**The Harvester** crawls manufacturer websites using Playwright and extracts device specs using a 5-model LLM fallback chain (local gemma4:e4b primary → NVIDIA NIM → Groq). Extracted records are stored in MongoDB.
```

- [ ] **Step 3: Update `README.md` line 35 (mermaid diagram)**

Replace:
```
    PARALLEL --> LLM[LLM Chain<br/>Groq → NVIDIA → qwen2.5:3b fallback<br/>per-provider semaphores]
```
with:
```
    PARALLEL --> LLM[LLM Chain<br/>gemma4:e4b → NVIDIA → Groq<br/>per-provider semaphores]
```

- [ ] **Step 4: Update `README.md` line 129**

Replace:
```
- **`ollama-init`** — one-shot container that pulls `qwen2.5:3b` (~2 GB) on first run
```
with:
```
- **`ollama-init`** — one-shot container that pulls `gemma4:e4b` on first run
```

(Size estimate dropped — gemma4:e4b is too new to have a confirmed size; Docker will report actual on first pull.)

- [ ] **Step 5: Update `README.md` line 131**

Replace:
```
Cloud LLMs (Groq, NVIDIA NIM) handle extraction by default. The local `qwen2.5:3b` only runs when both cloud providers are unreachable.
```
with:
```
Local `gemma4:e4b` is the primary extractor. Cloud LLMs (Groq, NVIDIA NIM) absorb overflow when the Ollama semaphore is saturated and serve as full fallback when the local model fails.
```

- [ ] **Step 6: Update `README.md` line 199**

Replace:
```
- LLM-powered extraction with 6-model fallback chain (Groq → NVIDIA → local qwen2.5:3b fallback)
```
with:
```
- LLM-powered extraction with 5-model fallback chain (local gemma4:e4b primary → NVIDIA → Groq)
```

- [ ] **Step 7: Update `CLAUDE.md` line 37**

Replace:
```
First run downloads `qwen2.5:3b` (~2GB) into the `ollama_models` named volume via the `ollama-init` sidecar. Cloud LLMs (Groq, NVIDIA) are primary; the local model only runs when cloud is unreachable. GPU passthrough is opt-in via `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up` (requires NVIDIA Container Toolkit).
```
with:
```
First run downloads `gemma4:e4b` into the `ollama_models` named volume via the `ollama-init` sidecar. The local `gemma4:e4b` is the primary extractor; cloud LLMs (Groq, NVIDIA) absorb overflow and serve as fallback. GPU passthrough is opt-in via `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up` (requires NVIDIA Container Toolkit).
```

- [ ] **Step 8: Update `CLAUDE.md` line 58**

Replace:
```
  → LLM extraction (6-model fallback chain) → normalize → validate → GUDID JSON (harvester/output/)
```
with:
```
  → LLM extraction (5-model fallback chain) → normalize → validate → GUDID JSON (harvester/output/)
```

- [ ] **Step 9: Update `CLAUDE.md` lines 65-70 (chain block)**

Replace lines 65-70 (the six numbered chain lines inside the code fence):
```
1. Groq   llama-3.3-70b-versatile       (primary, fastest cloud)
2. Groq   llama-3.1-8b-instant          (separate Groq limits)
3. NVIDIA meta/llama-3.3-70b-instruct   (40 RPM, generous limits)
4. NVIDIA mistralai/mistral-large       (40 RPM)
5. NVIDIA google/gemma-2-27b-it         (40 RPM)
6. Ollama qwen2.5:3b                    (local fallback, ~2GB)
```
with:
```
1. Ollama gemma4:e4b                    (primary, most capable per user judgment)
2. NVIDIA mistralai/mistral-large       (~123B, strongest cloud)
3. Groq   llama-3.3-70b-versatile       (70B, fastest provider)
4. NVIDIA meta/llama-3.3-70b-instruct   (70B, slower-provider backup)
5. Groq   llama-3.1-8b-instant          (8B, last resort)
```

- [ ] **Step 10: Update `CLAUDE.md` line 73**

Replace:
```
Cloud-first: Groq/NVIDIA handle normal load; local Ollama only runs when both cloud providers are unreachable. Tries top-to-bottom. On rate limit < 60s: retries once. On daily limit or long wait: disables model for session, moves to next. Groq/NVIDIA use same OpenAI-compatible `_openai_request()`. Ollama uses `/api/chat`.
```
with:
```
Local-first: gemma4:e4b is primary; cloud models absorb overflow when the Ollama semaphore is saturated and serve as fallback when the local model fails. Tries top-to-bottom. On rate limit < 60s: retries once. On daily limit or long wait: disables model for session, moves to next. Groq/NVIDIA use same OpenAI-compatible `_openai_request()`. Ollama uses `/api/chat`.
```

- [ ] **Step 11: Update `CLAUDE.md` line 112**

Replace:
```
| **LLM Extractor** (`pipeline/llm_extractor.py`) | Primary extractor, 6-model chain | Every file in pipeline |
```
with:
```
| **LLM Extractor** (`pipeline/llm_extractor.py`) | Primary extractor, 5-model chain | Every file in pipeline |
```

- [ ] **Step 12: Verify no stragglers in tracked source/docs**

```bash
grep -rn "qwen2.5:3b\|google/gemma-2-27b-it\|6-model" \
    harvester/src/ docker/ CLAUDE.md README.md .env.example \
    --exclude-dir=tests
```

Expected output: empty.

(The test file `harvester/src/pipeline/tests/test_llm_extractor_env.py` legitimately contains `"qwen2.5:3b"` and `"google/gemma-2-27b-it"` as forbidden-value assertions — those are correct. The `--exclude-dir=tests` filter removes them from the check.)

- [ ] **Step 13: Commit**

```bash
git add .env.example README.md CLAUDE.md
git commit -m "docs(llm-chain): update chain references to gemma4:e4b primary, 5-model"
```

---

### Task 5: Final verification

**Files:** none modified.

- [ ] **Step 1: Run the full chain test suite**

```bash
cd harvester/src && python -m pytest pipeline/tests/test_llm_extractor_env.py -v
```

Expected: 3 passed.

- [ ] **Step 2: Sanity import check**

```bash
cd harvester/src && python -c "from pipeline.llm_extractor import MODEL_CHAIN, get_first_available_model; assert len(MODEL_CHAIN) == 5; assert MODEL_CHAIN[0]['model'] == 'gemma4:e4b'; print('OK', len(MODEL_CHAIN), 'models, primary =', MODEL_CHAIN[0]['model'])"
```

Expected: `OK 5 models, primary = gemma4:e4b`

- [ ] **Step 3: Cross-file grep sanity**

```bash
grep -rn "qwen2.5:3b\|google/gemma-2-27b-it" \
    harvester/src/ docker/ CLAUDE.md README.md .env.example \
    --exclude-dir=tests
```

Expected: empty. (Test file matches are expected and excluded — those are the forbidden-value assertions.)

```bash
grep -rn "6-model" harvester/src/ docker/ CLAUDE.md README.md .env.example
```

Expected: empty.

- [ ] **Step 4: Confirm git log shows the four feature commits**

```bash
git log --oneline -5
```

Expected (most recent first): `docs(llm-chain): ...`, `chore(docker): ...`, `feat(llm-chain): ...`, `test(llm-chain): ...`, plus the spec commit from earlier.

No commit needed for this task — it's verification only.

---

## Notes for the Implementer

- **Do NOT** edit historical files: `harvester/log-files/*.log`, `docs/superpowers/specs/2026-04-09-*`, `docs/superpowers/specs/2026-04-20-*`, `docs/superpowers/plans/2026-04-09-*`, `docs/superpowers/plans/2026-04-20-*`. They are snapshots in time.
- **Do NOT** rebuild Docker or `ollama pull` the new model as part of this plan — that's a follow-up manual verification the user will run. The plan's job is to update text and code.
- The `_provider_sems` dict in `llm_extractor.py` (lines 36-40 in the current file) does NOT need to change — its keys (`"ollama"`, `"groq"`, `"nvidia"`) are unchanged.
- `parallel_batch.py`, `runner.py`, and other consumers of `MODEL_CHAIN` do not need changes — they index by provider/model name, not position.
