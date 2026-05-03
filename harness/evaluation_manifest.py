from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

THESIS_ONE_LINER = (
    "Agentic systems can execute capability-boundary violations under multi-turn pressure; "
    "this evaluation measures attack success, detection, false positives, and cost on a "
    "fixed scenario corpus with pre-execution enforcement and structured traces."
)


def write_evaluation_manifest(
    out_root: Path,
    *,
    scenarios_path: Path,
    defenses: list[str],
    model: str,
    provider: str,
    k: int,
    live_llm: bool,
    axes: list[str] | None,
) -> Path:
    """Forkable manifest: thesis, doc pointers, artifact paths, run metadata."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "thesis_one_liner": THESIS_ONE_LINER,
        "run": {
            "provider": provider,
            "model": model,
            "k": k,
            "live_llm": live_llm,
            "axes_filter": axes,
            "defenses": defenses,
            "scenarios_path": str(scenarios_path),
        },
        "documentation": {
            "citation_ready_framework": "docs/citation_ready_framework.md",
            "trace_schema": "docs/trace_schema.md",
            "enforcement_gate": "docs/enforcement_gate.md",
            "external_benchmarks": "docs/external_benchmarks_positioning.md",
            "limitations": "docs/limitations.md",
            "corpus_contract": "scenarios/CORPUS_CONTRACT.md",
            "scenario_metadata_schema": "scenarios/scenario_metadata.schema.json",
            "observability_overview": "docs/observability_framework.md",
        },
        "artifacts": {
            "summary_jsonl": "summary.jsonl",
            "defense_landscape_matrix": "defense_landscape_matrix.json",
            "degradation_curves": "degradation_curves.json",
            "coverage_complementarity": "coverage_complementarity.json",
            "per_cell_trace": "trace.jsonl (under each scenario x defense directory)",
            "per_turn_agent_log": "runtime/**/agent_turn_*.jsonl",
        },
        "enforcement": {
            "mode": "pre_execution_tool_policy",
            "code": "orchestrators/minimal_agent.py",
            "description": "tool_policy runs before RPC; block verdict prevents execution and gates attack success.",
        },
    }
    out_path = out_root / "evaluation_manifest.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out_path
