# External benchmarks positioning

The **internal observability corpus** (`scenarios/scenarios.json`, axes A–H) is designed for controlled, repeatable measurement of **capability-boundary violations** under multi-turn tool use, with **pre-execution enforcement** and **paired benign** scenarios.

Public agent safety suites serve complementary roles:

| Track | Role relative to this repo |
| --- | --- |
| **AgentDojo** | Broad agentic tasks and injections; useful for regression coverage on general tool misuse. This repo’s scenarios are smaller and axis-labeled for mechanism-specific claims. |
| **CAMEL / similar** | Multi-agent or role-based settings; good for interaction complexity. Our harness fixes principals and capabilities to isolate boundary semantics. |
| **Fides / governance case studies** | Organizational policy narratives; align with “who may act for whom.” We encode capability strings and approved tool lists explicitly for automation. |

**Campaign wiring:** `scripts/run_production_campaign.sh` can stage external roots (`AGENTDOJO_ROOT`, `CAMEL_ROOT`, `FIDES_ROOT`). `scripts/merge_production_report.py` merges manifest stages into `unified_report.json` under `externals`.

When citing results, distinguish **internal matrix metrics** (ASR / detection / FPR on `scenarios.json`) from **external suite scores**, which use those projects’ native success criteria.
