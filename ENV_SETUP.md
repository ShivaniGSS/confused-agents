# ENV_SETUP.md — Models, API keys, caching, determinism

This document specifies the LLM environment for the artifact. All
three API providers (Anthropic, OpenAI, Together AI) are used; each
plays a specific role.

---

## 1. The three roles

The evaluation uses LLM calls in three roles:

### Primary frontier model
Used for the main evaluation. The agent's reasoning runs on this
model in all headline tables (Tables 1–6 in `EMPIRICAL_DESIGN.md`).

**Default:** `claude-opus-4-5-20250929` via Anthropic API.

**Alternative (sensitivity ablation):** `gpt-4-turbo-2024-04-09` via
OpenAI API.

### Open-model ablation
Used for Day 6 ablation only. Confirms results are not specific to
frontier-model behavior.

**Default:** `meta-llama/Llama-3.3-70B-Instruct-Turbo` via Together AI.

### CaMeL-like baseline planner
**No LLM used.** The planner is deterministic per `BASELINES.md` §2.
This is a deliberate decision; do not introduce LLM calls into the
baseline implementation.

---

## 2. API keys and environment

The repo's `.env.example` lists required keys without values:

```bash
# Required for primary frontier model
ANTHROPIC_API_KEY=

# Required for sensitivity ablation
OPENAI_API_KEY=

# Required for open-model ablation
TOGETHER_API_KEY=

# Optional — controls which model the harness uses by default
PRIMARY_MODEL=claude
# Valid values: claude | openai

# Optional — caching directory; default is results/llm_cache/
LLM_CACHE_DIR=results/llm_cache
```

The reviewer copies `.env.example` to `.env` and fills in keys.
`scripts/run_all.sh` sources `.env` before running anything.

`scripts/verify_anonymity.sh` (CLAUDE.md §12) must not log API keys
to any file the artifact ships with. The cache directory is
gitignored.

---

## 3. Determinism

Per CLAUDE.md §1.6, `temperature=0` is the rule. Per-provider details:

### Anthropic
- `temperature=0`
- Pinned model string: `claude-opus-4-5-20250929`
- Set `max_tokens` explicitly (default 4096; tool-call responses are
  small so this is rarely binding).
- `top_p` default; we don't change it.

### OpenAI
- `temperature=0`
- Pinned model string: `gpt-4-turbo-2024-04-09`
- `seed=42` (OpenAI honors this; Anthropic doesn't have an equivalent
  but `temperature=0` + caching gives effective determinism).
- `top_p=1`

### Together AI
- `temperature=0`
- Pinned model string: `meta-llama/Llama-3.3-70B-Instruct-Turbo`
- Together AI's open-model determinism varies. k=10 + Wilson CIs
  are the response.

Pin every model string in `requirements.txt` comments and in
`harness/run_attack.py`'s constants. Do not let model names drift.

---

## 4. Caching scheme

Aggressive caching is essential. The first full run is the budget;
subsequent runs hit cache and complete in minutes.

### Cache key

`SHA-256(provider | model | temperature | seed | system_prompt |
messages | tools | other_settings)` → hex string.

Implemented in `harness/llm_client.py`:

```python
def cache_key(provider, model, temperature, seed, system, messages, tools, settings):
    payload = json.dumps({
        "provider": provider, "model": model,
        "temperature": temperature, "seed": seed,
        "system": system, "messages": messages,
        "tools": tools, "settings": settings,
    }, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()
```

### Cache directory layout

```
results/llm_cache/
  <provider>/
    <hash[:2]>/
      <hash>.json   # cached response
```

Sharded by hash prefix to keep filesystem operations fast.

### Cache file contents

```json
{
  "key": "<full hash>",
  "request": { "provider": "...", "model": "...", "temperature": 0, ... },
  "response": { ... raw provider response ... },
  "cached_at": "2026-04-26T12:00:00Z"
}
```

### Cache hits and misses

- On miss: make the API call, store the response, return it.
- On hit: return the cached response. Increment a counter for cache-hit
  reporting in run summaries.
- Never serve stale cache: cache entries are immutable. To
  invalidate, delete the cache directory. The cache is correct by
  construction — if the request is identical, the response should be
  identical (modulo provider non-determinism, which `temperature=0`
  largely eliminates).

### What's cacheable

- All LLM calls during attack runs and benign runs.
- All LLM calls during the CaMeL-like baseline (none, since planner is
  deterministic).
- Mock-server tool calls are NOT cached — they're already
  deterministic via SQLite snapshot/restore.

### Cache size

Estimated 500 MB for a full evaluation pass. Storage budget allows
this; gitignore the cache directory.

---

## 5. Rate-limit handling

API rate limits will hit during the first full run.

### Anthropic
Token-bucket rate limit per minute. Implement exponential backoff:
```python
def call_with_backoff(fn, max_retries=5):
    for i in range(max_retries):
        try: return fn()
        except RateLimitError as e:
            wait = min(60, 2 ** i)
            time.sleep(wait)
    raise
```

### OpenAI
Both RPM and TPM limits. Backoff handles RPM. For TPM, batch fixtures
that hit the limit and resume.

### Together AI
Generally less aggressive limits, but may have intermittent capacity
issues for the 70B model. Backoff handles both.

Per CLAUDE.md §1.7 (no silent fallbacks), the backoff utility raises
after `max_retries`. The harness logs the failure and surfaces;
nobody auto-retries forever.

---

## 6. Cost estimate

Approximate token counts and costs for a full evaluation pass.

### Per attack run (k=1)
- Input: ~3,000 tokens (system + tool defs + fixture data + history).
- Output: ~500 tokens (tool-call decisions + reasoning).
- Anthropic Opus 4.5: ~$0.07 per run.
- OpenAI gpt-4-turbo: ~$0.05 per run.
- Llama 3.3 70B via Together: ~$0.01 per run.

### Full pass (per `EMPIRICAL_DESIGN.md` §4)
- 24 fixtures × 6 defenses × 2 orchestrators × k=10 = 2,880 runs per
  primary model.
- Plus 50 benign × 6 defenses × 2 orchestrators × k=10 = 6,000 runs
  per primary model.
- Plus open-model ablation: ~1,440 runs.
- Total ≈ 10,300 runs.

### Estimated cost (first pass, no cache hits)
- Primary frontier model (Anthropic): ~$700.
- Sensitivity ablation (OpenAI): ~$500.
- Open-model ablation (Together): ~$15.
- Total first pass: ~$1,200.

### Estimated cost (subsequent passes)
With cache hits, near zero. Cache invalidation only when fixtures or
prompts change.

These are upper bounds. In practice, the model refusal heterogeneity
discussed in CLAUDE.md §13 means many runs terminate early; actual
token counts are lower. Budget for the upper bound.

---

## 7. Reproducing the artifact

`scripts/run_all.sh` is the single entry point per CLAUDE.md §11. Its
sequence:

1. Source `.env`.
2. Verify all required keys are present (refuse to run if missing).
3. Run anonymity check (refuse to run if hits).
4. Snapshot the SQLite stores for each fixture.
5. Run the corpus across all defense configurations × orchestrators ×
   models per `EMPIRICAL_DESIGN.md` §4. Caching means re-runs are
   fast.
6. Run the benign workload similarly.
7. Run the commit-race case study.
8. Run the four critical ablations.
9. Generate all tables and figures via `notebooks/generate_tables.ipynb`.
10. Write outputs to `paper_outputs/`.

Total wall time on first run: 4–8 hours depending on rate-limit hits.
Subsequent runs: 15–30 minutes (regenerating tables from cache).

---

## 8. What lives in `.env` vs config

- `.env`: secrets only (API keys). User-specific. Never committed.
- `harness/config.py`: model strings, default parameters, cache
  directory, irreversibility tagging table. Repo-tracked.
- `attacks/fixtures/<id>/axes.json`: per-fixture configuration.
- `capguard/baselines/plan_templates/<id>.json`: per-fixture plan
  templates for the CaMeL-like baseline.

A reviewer should never need to edit anything outside `.env` to
reproduce the paper.

---

## 9. Expected behavior under partial keys

If only `ANTHROPIC_API_KEY` is set:
- Primary frontier evaluation runs.
- OpenAI sensitivity ablation is skipped with a warning.
- Open-model ablation is skipped with a warning.
- Tables and figures are generated from available data; the paper's
  cross-model robustness claims are footnoted as not fully
  reproduced.

If only `TOGETHER_API_KEY` is set:
- Primary evaluation cannot run (frontier model is required for the
  headline numbers).
- Reviewer is told to obtain at least Anthropic or OpenAI access for
  full reproduction.

Per CLAUDE.md §1.7, `run_all.sh` raises rather than silently
producing incomplete outputs. Surface the missing-key situation
clearly.

---

End of ENV_SETUP.md.
