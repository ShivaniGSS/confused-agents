# Observability Framework (A-H)

This framework adds an explicit multi-turn observability evaluation surface alongside the existing fixture harness.

## What is included

- `scenarios/scenarios.json`
  - Full scenario-count catalog aligned to the plan:
    - Axis A: 3
    - Axis B: 2
    - Axis C: 2
    - Axis D: 3
    - Axis E: 2
    - Axis F: 2
    - Axis G: 2
    - Axis H: 2
- `defenses/`
  - `none`, `model_safety`, `integrity_only`, `camel_style`, `capguard`, `trajectory_monitor`, `full_stack`.
- `harness/trace.py`
  - JSONL trace entry writer used for per-turn observability logs.
- `harness/multi_turn_runner.py`
  - Multi-turn scenario runner with all-defense decision capture per tool call.
- `harness/adaptive_attacker.py`
  - Adaptive attacker hook for axis-E style strategy updates.
- `harness/session_manager.py`
  - Cross-session state container for temporal decoupling experiments.
- `harness/run_observability_matrix.py`
  - CLI for scenario x defense matrix execution.
- `scripts/run_observability_matrix.sh`
  - Convenience wrapper.

## Run

```bash
bash scripts/run_observability_matrix.sh
```

Production-hardened campaign (retries, checkpoints, staged axes/models, unified report):

```bash
bash scripts/run_production_campaign.sh
```

Or direct CLI:

```bash
PYTHONPATH="$PWD" python -m harness.run_observability_matrix \
  --scenarios "$PWD/scenarios/scenarios.json" \
  --defenses none,model_safety,integrity_only,camel_style,capguard,trajectory_monitor,full_stack \
  --out "$PWD/results/observability/$(date +%Y%m%d-%H%M%S)"
```

### Real Stack Modes

- Default mode uses `ScriptedClient` but executes through the real orchestrator and mock MCP servers.
- Set `--live-llm` to run with a real provider client (`--provider`, `--model`).
- Live mode requires provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `TOGETHER_API_KEY`).
- For publication-style rates and CIs, pass **`--k 4`** (or set `K=4`); `k=1` is useful for debugging only.

## Output

- `trace.jsonl` per `scenario x defense` cell
- `summary.jsonl` matrix-level summary with:
  - `scenario_id`
  - `axis`
  - `defense`
  - `run_type` (`attack` or `benign`)
  - `success`
  - `blocked`
  - `detection_turn`
  - `turns_executed`
  - `wall_time_ms` (orchestrator + agent loop, summed over scenario turns)
  - `llm_prompt_tokens` / `llm_completion_tokens` (when the provider returns usage; else `0`)
- `defense_landscape_matrix.json`
  - Aggregated by `axis x defense`:
    - attack success rate
    - detection rate
    - false positive rate
    - mean detection horizon
    - mean attack-run wall time and token totals (for cost / rigor tables)
- `coverage_complementarity.json`
  - Axis semantics, scenario ids per axis, defense mechanism blurbs, and full matrix cells for complementarity claims
- `evaluation_manifest.json`
  - Thesis one-liner, doc pointers, artifact index, enforcement summary (citation fork bundle)
- `degradation_curves.json`
  - Aggregated by `axis x defense x axis_param`:
    - detection rate
    - attack success rate
    - false positive rate
- `campaign_manifest.jsonl` (production campaign)
  - stage-by-stage status with artifact paths
- `unified_report.json` (production campaign)
  - merged summary over observability and external benchmark tracks (includes `evaluation_artifacts` when manifest/coverage files are present beside the defense matrix)

## Citation-ready evaluation

For paper-style claims (thesis, semantics layers, corpus contract, limitations, trace/enforcement specs), see [citation_ready_framework.md](citation_ready_framework.md).
