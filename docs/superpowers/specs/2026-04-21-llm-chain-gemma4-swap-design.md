# LLM Chain Swap — gemma4:e4b Primary, Drop qwen2.5:3b and gemma-2-27b

**Date:** 2026-04-21
**Author:** Jason
**Status:** Spec — pending plan

## Problem

The current `MODEL_CHAIN` in `harvester/src/pipeline/llm_extractor.py` is six entries: five cloud models plus `qwen2.5:3b` as a local last-resort fallback. The user wants:

1. The local model swapped from `qwen2.5:3b` to `gemma4:e4b` (an "extremely new" model the user trusts and uses elsewhere via `ask_gemma`).
2. `gemma4:e4b` promoted to the **primary** position because the user judges it the most capable model in the chain.
3. `nvidia google/gemma-2-27b-it` removed entirely (the new gemma4 supersedes it).
4. The remaining models reordered by **raw capability** rather than provider speed.

## Goal

Replace `qwen2.5:3b` with `gemma4:e4b`, promote it to position 0, drop `google/gemma-2-27b-it`, and reorder the remaining cloud entries by capability. Update Docker model pull, the chain test, and all relevant docs to match. No changes to extraction logic, semaphores, or worker counts.

## Non-Goals

- No changes to the two-pass extraction flow, prompts, schemas, or HTTP helpers.
- No changes to `EXTRACT_WORKERS`, `GROQ_CONCURRENCY`, or `NVIDIA_CONCURRENCY`.
- No changes to historical log files or historical spec/plan documents that mention `qwen2.5:3b` — those are snapshots and stay as-is.
- No changes to `pipeline/parallel_batch.py` (it consumes the chain via the public API; reordering is transparent).

## New `MODEL_CHAIN`

| Pos | Provider | Model | Rationale |
|-----|----------|-------|-----------|
| 0 | `ollama` | `gemma4:e4b` | User-judged most capable; primary |
| 1 | `nvidia` | `mistralai/mistral-large` | ~123B params (Mistral Large 2), strongest cloud option |
| 2 | `groq` | `llama-3.3-70b-versatile` | 70B Llama 3.3, fastest provider for this model |
| 3 | `nvidia` | `meta/llama-3.3-70b-instruct` | Same 70B model, slower-provider backup |
| 4 | `groq` | `llama-3.1-8b-instant` | 8B fallback; smallest, last cloud resort |

Length: **5 entries** (was 6). Drops `nvidia google/gemma-2-27b-it`.

### Trade-off: capability-first instead of speed-first

The original chain put `groq llama-3.3-70b-versatile` first because Groq is the fastest cloud provider. The new ordering optimizes for **capability** instead. Failures will fall through more slowly because the next-in-line is also a large model. This is the intended behavior.

## Concurrency

Unchanged from current values:

```python
EXTRACT_WORKERS = 4
OLLAMA_CONCURRENCY = 1   # serialize on CPU-only hosts
GROQ_CONCURRENCY = 3
NVIDIA_CONCURRENCY = 4
```

### Implication of `OLLAMA_CONCURRENCY = 1` with local-first

Workers acquire the provider semaphore non-blocking. With gemma4 at position 0 and `OLLAMA_CONCURRENCY = 1`:

- Worker A acquires the Ollama semaphore → uses gemma4.
- Workers B, C, D fail to acquire → fall through to `mistralai/mistral-large`.

Net effect per batch of 4 files: roughly 1 file goes through local gemma4 (slow, CPU-bound), 3 go through cloud. This is the chosen behavior. We are **not** bumping `OLLAMA_CONCURRENCY` — the user explicitly chose option A in brainstorming.

## Files to Change

### 1. `harvester/src/pipeline/llm_extractor.py`

- **Lines 19-26 (`MODEL_CHAIN`):** rewrite per the table above.
- **Lines 28-34 (concurrency comment block):** update the wording from "cloud-first chain + single small local fallback" to reflect that gemma4 is now primary and the local model is the user-preferred most-capable option. Keep the rate-limit notes for Groq/NVIDIA. Keep the Ollama-stays-at-1 note.

No other changes in this file. Semaphores key on `entry["provider"]`, which is unchanged. The fallthrough logic in `_llm_request` already iterates the chain in list order, so reordering is purely declarative.

### 2. `docker/docker-compose.yml`

- **Line 37:** change `ollama pull qwen2.5:3b` → `ollama pull gemma4:e4b`.
- No changes to volumes, services, or env vars.

### 3. `harvester/src/pipeline/tests/test_llm_extractor_env.py`

The existing test `test_model_chain_is_cloud_first_with_small_local_fallback` (lines 19-41) hardcodes the old chain. It needs to be rewritten:

- Rename to `test_model_chain_is_local_first_capability_ordered` (or similar — "cloud-first" no longer describes the chain).
- Update docstring to reflect local-first capability ordering.
- Change `assert len(chain) == 6` → `assert len(chain) == 5`.
- Replace positional asserts to match the new table:
  - `chain[0] == {"provider": "ollama", "model": "gemma4:e4b"}`
  - `chain[1] == {"provider": "nvidia", "model": "mistralai/mistral-large", "env_key": "NVIDIA_API_KEY"}`
  - `chain[2] == {"provider": "groq", "model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY"}`
  - `chain[3] == {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct", "env_key": "NVIDIA_API_KEY"}`
  - `chain[4] == {"provider": "groq", "model": "llama-3.1-8b-instant", "env_key": "GROQ_API_KEY"}`
- Update the "removed models must not appear" block:
  - Remove `assert "gemma4" not in model_names` (gemma4 is now allowed; specifically `gemma4:e4b`).
  - Add `assert "qwen2.5:3b" not in model_names`.
  - Add `assert "google/gemma-2-27b-it" not in model_names`.
  - Keep `assert "qwen2.5:7b" not in model_names`.
  - Drop the `"mistral" not in model_names` line — it's misleading because the chain has `mistralai/mistral-large` (it currently passes only because the assertion checks list membership of the bare string `"mistral"`, not substring).

The other two tests in the file (`test_ollama_url_defaults_to_localhost`, `test_ollama_url_respects_env_override`) are unaffected.

### 4. `CLAUDE.md`

Three updates:

- **LLM Fallback Chain section** (the numbered list of 6 models): rewrite as the new 5-entry table or list, ordered by capability with gemma4:e4b at #1.
- **"Cloud-first" sentence** that begins "Cloud-first: Groq/NVIDIA handle normal load…": rephrase to reflect that gemma4:e4b is primary now, with cloud models as fallback when the Ollama semaphore is saturated.
- **"6-model fallback chain" / "(6-model fallback chain)" mentions** (Architecture diagram caption and elsewhere): change to **5-model**.
- **First-run download note:** "First run downloads `qwen2.5:3b` (~2GB)…" → update to `gemma4:e4b` and remove the size estimate (unknown — Docker will report actual size on first pull).

### 5. `README.md`

Five mentions of `qwen2.5:3b` (lines 17, 35, 129, 131, 199) plus a "6-model" count mention. Update all to:

- Replace `qwen2.5:3b` with `gemma4:e4b`.
- Update the "6-model fallback chain" wording to "5-model fallback chain".
- Reorder the chain description in the architecture text/diagram so the local model leads (matches the new chain ordering).
- Update the `ollama-init` description (line 129): swap model name; remove the "(~2 GB)" size estimate.
- Update line 131 ("Cloud LLMs handle extraction by default. The local `qwen2.5:3b` only runs when both cloud providers are unreachable.") — this sentence is **no longer accurate** with gemma4 as primary. Rephrase to: gemma4 handles extraction first; cloud models pick up overflow when the Ollama semaphore is saturated, and serve as full fallback when gemma4 fails.

### 6. `.env.example`

- **Line 12:** comment "# ── LLM APIs (fallback chain: Groq → NVIDIA → local qwen2.5:3b) ─────────────" → update model name and reorder if desired (the chain order in this comment is decorative; updating to reflect local-first is preferred for accuracy).

## Out of Scope (do not touch)

- `harvester/log-files/harvest_*.log` — historical run logs.
- `docs/superpowers/specs/2026-04-09-docker-containerization-design.md` — historical spec.
- `docs/superpowers/plans/2026-04-09-docker-containerization.md` — historical plan.
- `docs/superpowers/specs/2026-04-20-portable-docker-design.md` — historical spec.
- `docs/superpowers/plans/2026-04-20-portable-docker.md` — historical plan.

These are snapshots in time and should not be retroactively rewritten.

## Risks and Edge Cases

- **gemma4:e4b pull may fail or take long on first Docker run.** The model is new; Docker pull duration and final image size are unknown. If the pull fails, the existing pipeline already handles it: `_ollama_request` catches `ConnectionError` and disables the model for the session, then falls through to cloud. So a failed pull degrades gracefully — it does not break the pipeline. Worth a brief manual verification on first compose build.
- **Cold-start latency on every batch.** Until the first 4 files have run, the OS has cold gemma4 weights. The first file in each fresh container start will be slower than under the old chain. Steady-state batches are unchanged.
- **Cloud cost / rate-limit profile shifts.** With gemma4 absorbing 1 of every 4 files, cloud usage per batch drops ~25%. This is a side benefit, not a goal.
- **No backwards-compat shim.** The `MODEL_CHAIN` list is internal; no consumers index it positionally outside the test we are rewriting. Safe to change in place.

## Verification

After implementation, the following must pass:

1. `pytest harvester/src/pipeline/tests/test_llm_extractor_env.py` — all three tests green.
2. Manual: `cd docker && docker compose up` → confirm `ollama-init` logs show `gemma4:e4b` pulled successfully and "Model ready".
3. Manual: run one extraction end-to-end (`python harvester/src/pipeline/runner.py` against a known input) and confirm the log line `Extraction succeeded with gemma4:e4b (ollama)` appears for the first file.
4. Grep sanity: `grep -r "qwen2.5:3b" harvester/ docker/ CLAUDE.md README.md .env.example` returns no matches outside `harvester/log-files/` and `docs/superpowers/`.

## Open Questions

None. All clarifications resolved during brainstorming:
- Model tag: `gemma4:e4b` (confirmed).
- Drop `google/gemma-2-27b-it`: yes (confirmed).
- Concurrency: keep `OLLAMA_CONCURRENCY = 1` (confirmed, option A).
- Capability ordering for cloud models: approved (mistral-large > llama-3.3-70b groq > llama-3.3-70b nvidia > llama-3.1-8b).
