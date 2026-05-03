from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from harness.metrics import Proportion


def generate_defense_matrix(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in summary_rows:
        grouped[(row["axis"], row["defense"])].append(row)

    out: list[dict[str, Any]] = []
    for (axis, defense), rows in sorted(grouped.items()):
        attack_rows = [r for r in rows if r.get("run_type") == "attack"]
        benign_rows = [r for r in rows if r.get("run_type") == "benign"]
        n = len(attack_rows)
        detections = sum(1 for r in attack_rows if int(r.get("detection_turn", -1)) >= 0)
        successes = sum(1 for r in attack_rows if bool(r.get("success", False)))
        horizons = [int(r["detection_turn"]) for r in attack_rows if int(r.get("detection_turn", -1)) >= 0]
        benign_n = len(benign_rows)
        benign_detections = sum(1 for r in benign_rows if int(r.get("detection_turn", -1)) >= 0)
        executed_attack_rows = [
            r for r in attack_rows if str(r.get("model_safety_outcome", "")) == "executed"
        ]
        n_ex = len(executed_attack_rows)
        detections_given_executed = sum(
            1 for r in executed_attack_rows if int(r.get("detection_turn", -1)) >= 0
        )
        det_given_ex = Proportion(successes=detections_given_executed, n=n_ex)
        asr = Proportion(successes=successes, n=n)
        det = Proportion(successes=detections, n=n)
        fpr = Proportion(successes=benign_detections, n=benign_n)
        asr_lo, asr_hi = asr.wilson_ci()
        det_lo, det_hi = det.wilson_ci()
        fpr_lo, fpr_hi = fpr.wilson_ci()
        if n_ex > 0:
            dge_lo, dge_hi = det_given_ex.wilson_ci()
            det_given_rate = det_given_ex.rate
        else:
            dge_lo = dge_hi = None
            det_given_rate = None
        ms_counts = {"executed": 0, "refused": 0, "partial": 0, "failed": 0}
        for r in attack_rows:
            lbl = str(r.get("model_safety_outcome", "failed"))
            if lbl not in ms_counts:
                lbl = "failed"
            ms_counts[lbl] += 1
        wall_ms = [int(r.get("wall_time_ms", 0)) for r in attack_rows]
        ptok = [int(r.get("llm_prompt_tokens", 0)) for r in attack_rows]
        ctok = [int(r.get("llm_completion_tokens", 0)) for r in attack_rows]
        out.append(
            {
                "axis": axis,
                "defense": defense,
                "attack_n": n,
                "benign_n": benign_n,
                "attack_success_rate": asr.rate if n else 0.0,
                "attack_success_ci_lo": asr_lo,
                "attack_success_ci_hi": asr_hi,
                "detection_rate": det.rate if n else 0.0,
                "detection_ci_lo": det_lo,
                "detection_ci_hi": det_hi,
                "attack_executed_n": n_ex,
                "detection_rate_given_attack_executed": det_given_rate,
                "detection_given_attack_executed_ci_lo": dge_lo,
                "detection_given_attack_executed_ci_hi": dge_hi,
                "false_positive_rate": fpr.rate if benign_n else 0.0,
                "false_positive_ci_lo": fpr_lo,
                "false_positive_ci_hi": fpr_hi,
                "mean_detection_horizon": (sum(horizons) / len(horizons)) if horizons else -1.0,
                "model_safety_executed_rate": (ms_counts["executed"] / n) if n else 0.0,
                "model_safety_refused_rate": (ms_counts["refused"] / n) if n else 0.0,
                "model_safety_partial_rate": (ms_counts["partial"] / n) if n else 0.0,
                "model_safety_failed_rate": (ms_counts["failed"] / n) if n else 0.0,
                "mean_wall_time_ms_attack": (sum(wall_ms) / n) if n else 0.0,
                "mean_llm_prompt_tokens_attack": (sum(ptok) / n) if n else 0.0,
                "mean_llm_completion_tokens_attack": (sum(ctok) / n) if n else 0.0,
            }
        )
    return out


def generate_complementarity_matrix(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per (scenario_id, defense) attack-run rollup: non-Cap blocks when Cap allows, layer unions."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in summary_rows:
        if row.get("run_type") != "attack":
            continue
        comp = row.get("complementarity")
        if not isinstance(comp, dict):
            continue
        sid = str(row.get("scenario_id", ""))
        defense = str(row.get("defense", ""))
        grouped[(sid, defense)].append(row)

    out: list[dict[str, Any]] = []
    for (scenario_id, defense), rows in sorted(grouped.items()):
        n = len(rows)
        mean_noncap_given_cap = sum(
            int(r["complementarity"].get("turns_noncap_blocked_given_cap_allowed", 0) or 0) for r in rows
        ) / n if n else 0.0
        layer_rates: dict[str, float] = {}
        for layer in ("spotlighting", "integrity_only", "camel_style", "capguard", "trajectory_monitor"):
            ever = sum(
                1
                for r in rows
                if bool((r.get("complementarity") or {}).get("layer_ever_blocked", {}).get(layer, False))
            )
            layer_rates[f"{layer}_ever_blocked_rate"] = ever / n if n else 0.0
        union_keys: set[str] = set()
        for r in rows:
            u = (r.get("complementarity") or {}).get("noncap_layers_union_when_cap_allowed") or []
            union_keys.update(str(x) for x in u)
        out.append(
            {
                "scenario_id": scenario_id,
                "defense": defense,
                "attack_n": n,
                "mean_turns_noncap_blocked_given_cap_allowed": mean_noncap_given_cap,
                **layer_rates,
                "distinct_noncap_union_keys_seen_across_runs": sorted(union_keys),
            }
        )
    return out


def write_defense_matrix(out_root: Path, summary_rows: list[dict[str, Any]]) -> Path:
    matrix = generate_defense_matrix(summary_rows)
    complementarity = generate_complementarity_matrix(summary_rows)
    out_path = out_root / "defense_landscape_matrix.json"
    out_path.write_text(
        json.dumps({"matrix": matrix, "complementarity": complementarity}, indent=2)
    )
    return out_path
