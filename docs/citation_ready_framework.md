# Citation-ready evaluation framework (checklist 1–8)

This repository is structured so a paper or report can cite **claims**, **definitions**, **metrics**, and **artifacts** without reverse-engineering the code. Each item below maps to concrete paths.

1. **Crisp thesis** — One sentence stating what is being measured and why it matters.  
   - Canonical copy: `harness/evaluation_manifest.py` (`THESIS_ONE_LINER`), echoed in each run’s `evaluation_manifest.json`.

2. **Three-layer semantics** — Separate **stress dimension** (axis A–H), **mechanism** (defense family), and **outcome metrics** (ASR, detection, FPR, horizons, cost).  
   - Axis definitions: `harness/coverage_matrix.py` (`AXIS_SEMANTICS`) and `coverage_complementarity.json`.  
   - Defense mechanisms: same module (`DEFENSE_MECHANISMS`).  
   - Metrics: `harness/matrix_generator.py`, `harness/metrics.py` (Wilson CIs).

3. **Complementarity and coverage** — Show which scenarios exist per axis and how defenses differ, without collapsing to a single scalar.  
   - Artifact: `coverage_complementarity.json` (from `harness/coverage_matrix.py`).  
   - Aggregated rates: `defense_landscape_matrix.json`.

4. **Corpus discipline** — Fixed catalog, paired attack/benign traces, explicit violation labels.  
   - Catalog: `scenarios/scenarios.json`.  
   - Contract: `scenarios/CORPUS_CONTRACT.md`.  
   - JSON Schema: `scenarios/scenario_metadata.schema.json`.

5. **Statistics and operational rigor** — Proportions with confidence intervals; token and wall-clock cost when the provider returns usage.  
   - CIs: `harness/metrics.py`.  
   - Per-step usage: `orchestrators/_llm.py` (`AssistantTurn.usage`), logged in agent JSONL (`orchestrators/minimal_agent.py`).  
   - Per-run roll-up: `AgentRunResult` / `RunResult` (`wall_time_ms`, `llm_prompt_tokens`, `llm_completion_tokens`) in `summary.jsonl`.

6. **External-benchmark positioning** — How this corpus relates to public suites (AgentDojo, CAMEL, Fides, etc.).  
   - `docs/external_benchmarks_positioning.md`.  
   - Production merge: `scripts/merge_production_report.py` (`externals` block).

7. **Limitations** — Scope, model dependence, corpus size, enforcement assumptions.  
   - `docs/limitations.md`.

8. **Forkable deliverables** — Trace schema, enforcement pattern, manifest listing artifacts and doc pointers.  
   - Trace: `docs/trace_schema.md`, `harness/trace.py`.  
   - Enforcement: `docs/enforcement_gate.md`, `orchestrators/minimal_agent.py` (`tool_policy`).  
   - Manifest: `evaluation_manifest.json` per observability run.

For the end-to-end runner overview, see `docs/observability_framework.md`.
