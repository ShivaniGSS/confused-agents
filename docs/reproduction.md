# Reproduction notes

Detailed reproduction guide for reviewers and curators of the artifact
hosted on `anonymous.4open.science`. Pairs with the high-level
README.md and the one-command `scripts/run_all.sh`.

## 1. Environment

Tested on macOS 14 (Apple silicon) and Linux x86_64 with Python 3.11.
Dependencies are pinned in `requirements.txt`. Total disk footprint
of `results/` after a full run is ~50 MB (mostly LLM-cache JSON).

```bash
git clone <anonymous-url> && cd confused-agents
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in API keys (see §2)
```

## 2. API keys

`run_all.sh` requires at least one of:

* `ANTHROPIC_API_KEY` — for the frontier-model runs (default
  `claude-sonnet-4-6`).
* `TOGETHER_API_KEY` — for the open-model ablation (default
  `meta-llama/Llama-3.3-70B-Instruct-Turbo`, Together serverless).

If only one is set, the corresponding run is skipped with a clear
message. No artifact step requires a real Gmail/Calendar/Drive/Payment
key — every tool surface is mocked locally.

## 3. CapGuard policy modules

Per the paper's contribution boundary (CLAUDE.md hard rule 8), the
following four modules are human-authored and must be in place before
running with `--capguard on`:

* `capguard/capability.py`
* `capguard/provenance.py`
* `capguard/policy.py`
* `capguard/irreversibility.py`

If any of these is still a stub, `run_all.sh` will exit on the first
attempted CapGuard call with a clear `NotImplementedError` (no silent
fallback — CLAUDE.md hard rule 7).

## 4. Determinism

* `temperature=0` everywhere supported (Anthropic, Together).
* Pinned model ids via env (`FRONTIER_MODEL`, `OPEN_MODEL`).
* Fresh SQLite snapshot/restore between runs (`harness/snapshot.py`).
* `k=10` repeats per attack with Wilson 95% CIs on every reported
  proportion.
* LLM responses cached on disk in `results/llm_cache/` keyed by hash
  of (prompt, tools, model, settings) so repeat runs do not re-bill.

LLM nondeterminism remains under `temperature=0` for some providers;
this is why `k=10` is the unit of analysis, not a single run.

## 5. Outputs

After `bash scripts/run_all.sh`:

* `results/baseline_frontier/corpus_summary.jsonl` — per-cell ASR, no CapGuard.
* `results/capguard_frontier/corpus_summary.jsonl` — per-cell ASR, CapGuard ON.
* `results/benign_frontier/benign_summary.jsonl` — per-item FPR, CapGuard ON.
* `results/ablation_openmodel/...` — open-model ablation if `TOGETHER_API_KEY` is set.
* `results/commit_race/{baseline,capguard}/summary.jsonl` — case study.
* `paper_outputs/table1_asr.csv`, `table2_fpr.csv`, `table3_latency.csv`,
  `commit_race.csv` — what the paper's tables draw from.

## 6. Anonymity

`scripts/verify_anonymity.sh` greps the repo for known deanonymizing
patterns. **Run it before any artifact upload.** A single hit is desk
rejection.

## 7. Known limitations / scope decisions

* The LangGraph orchestrator is wired but evaluation is reported only
  on the minimal orchestrator unless the user explicitly opts in.
  Section 13 of CLAUDE.md sanctions this fallback.
* Provenance label propagation is substring-based (over-approximation
  preferred over precision); see `capguard/provenance.py` and Section 4
  of the paper.
* Fixtures use synthetic principals only (`@example.test`,
  `@*-vendor.test`, etc.); no real-system data is touched.
