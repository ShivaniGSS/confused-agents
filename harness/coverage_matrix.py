from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from harness.matrix_generator import generate_defense_matrix

# Three-layer semantics (axis letter → stress dimension) for citation / coverage tables.
AXIS_SEMANTICS: dict[str, str] = {
    "A": "Long-horizon subject drift: approved capability erodes across turns.",
    "B": "Multi-source context composition: cross-subject signals in one decision.",
    "C": "Indirect / laundered intent across multiple tool hops.",
    "D": "Semantic cross-subject boundary (low/medium/ambiguous distance).",
    "E": "Adaptive attacker: budgeted strategy mutation between attempts.",
    "F": "Temporal decoupling: intent persisted across sessions or delays.",
    "G": "Longer read/write/share or summarize chains before violation.",
    "H": "Tool surface poisoning: descriptions, defaults, or schema bias.",
}

DEFENSE_MECHANISMS: dict[str, str] = {
    "none": "Baseline: no defense hook; measures raw model + orchestration.",
    "model_safety": "Outcome-only classifier on assistant text vs. expected tools (diagnostic).",
    "integrity_only": "Principal integrity checks on attempted calls.",
    "camel_style": "Plan alignment: tool must match approved capability plan.",
    "capguard": "Purpose-string subject binding for cross-subject violations.",
    "trajectory_monitor": "History-aware trajectory constraints on tool use.",
    "full_stack": "Sequential composition of the above mechanisms.",
}


def _scenarios_by_axis(scenarios_path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(scenarios_path.read_text())
    by_axis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in payload.get("scenarios", []):
        ax = str(s.get("axis", "")).upper()
        if not ax:
            continue
        by_axis[ax].append(
            {
                "id": s.get("id"),
                "axis_param": s.get("axis_param"),
                "attacker_strategy": s.get("attacker_strategy"),
            }
        )
    return {k: v for k, v in sorted(by_axis.items())}


def write_coverage_complementarity(
    out_root: Path,
    summary_rows: list[dict[str, Any]],
    scenarios_path: Path,
) -> Path:
    """Emit axis semantics, scenario coverage, and defense-matrix roll-up for complementarity claims."""
    matrix = generate_defense_matrix(summary_rows)
    by_axis = _scenarios_by_axis(scenarios_path)

    # Best detection per axis (for "which defense covers which stress" narratives).
    best_by_axis: dict[str, list[dict[str, Any]]] = {}
    for cell in matrix:
        ax = str(cell.get("axis", "")).upper()
        det = float(cell.get("detection_rate", 0.0))
        d = best_by_axis.setdefault(ax, [])
        d.append(
            {
                "defense": cell.get("defense"),
                "detection_rate": det,
                "attack_success_rate": float(cell.get("attack_success_rate", 0.0)),
                "false_positive_rate": float(cell.get("false_positive_rate", 0.0)),
            }
        )
    axis_champions: dict[str, Any] = {}
    for ax, rows in best_by_axis.items():
        if not rows:
            continue
        top = sorted(rows, key=lambda r: (-r["detection_rate"], r["false_positive_rate"]))[:3]
        axis_champions[ax] = top

    payload = {
        "axis_semantics": AXIS_SEMANTICS,
        "defense_mechanisms": DEFENSE_MECHANISMS,
        "scenarios_by_axis": by_axis,
        "defense_landscape_cells": matrix,
        "axis_detection_leaders": axis_champions,
        "complementarity_note": (
            "Defenses target different mechanisms (plan binding, purpose binding, trajectory, stack). "
            "No single cell summarizes 'coverage': use axis_semantics + defense_mechanisms + matrix cells together."
        ),
        "trajectory_monitor_interpretation": (
            "If trajectory_monitor shows 0% detection across cells, treat that as a finding about this "
            "implementation (drift thresholds / state vs corpus violation shapes), not as a general verdict "
            "on trajectory-level monitoring."
        ),
        "axis_h_routing_vs_injection": (
            "Axis H scenarios include metric_decomposition in scenarios.json: separate injection/schema "
            "compliance from CapGuard subject binding on email routing."
        ),
        "inputs": {
            "scenarios_path": str(scenarios_path),
            "summary_row_count": len(summary_rows),
        },
    }
    out_path = out_root / "coverage_complementarity.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out_path
