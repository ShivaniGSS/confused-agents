from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from harness.metrics import Proportion


def generate_degradation_curves(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in summary_rows:
        key = (
            row["axis"],
            row["defense"],
            row.get("param_name", ""),
            row.get("param_value", ""),
        )
        grouped[key].append(row)

    out: list[dict[str, Any]] = []
    for (axis, defense, pname, pvalue), rows in sorted(grouped.items()):
        attack_rows = [r for r in rows if r.get("run_type") == "attack"]
        benign_rows = [r for r in rows if r.get("run_type") == "benign"]
        n = len(attack_rows)
        detections = sum(1 for r in attack_rows if int(r.get("detection_turn", -1)) >= 0)
        successes = sum(1 for r in attack_rows if bool(r.get("success", False)))
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
        out.append(
            {
                "axis": axis,
                "defense": defense,
                "param_name": pname,
                "param_value": pvalue,
                "attack_n": n,
                "benign_n": benign_n,
                "detection_rate": det.rate if n else 0.0,
                "detection_ci_lo": det_lo,
                "detection_ci_hi": det_hi,
                "attack_executed_n": n_ex,
                "detection_rate_given_attack_executed": det_given_rate,
                "detection_given_attack_executed_ci_lo": dge_lo,
                "detection_given_attack_executed_ci_hi": dge_hi,
                "attack_success_rate": asr.rate if n else 0.0,
                "attack_success_ci_lo": asr_lo,
                "attack_success_ci_hi": asr_hi,
                "false_positive_rate": fpr.rate if benign_n else 0.0,
                "false_positive_ci_lo": fpr_lo,
                "false_positive_ci_hi": fpr_hi,
                "model_safety_executed_rate": (ms_counts["executed"] / n) if n else 0.0,
                "model_safety_refused_rate": (ms_counts["refused"] / n) if n else 0.0,
                "model_safety_partial_rate": (ms_counts["partial"] / n) if n else 0.0,
                "model_safety_failed_rate": (ms_counts["failed"] / n) if n else 0.0,
            }
        )
    return out


def write_degradation_curves(out_root: Path, summary_rows: list[dict[str, Any]]) -> Path:
    curves = generate_degradation_curves(summary_rows)
    out_path = out_root / "degradation_curves.json"
    out_path.write_text(json.dumps({"curves": curves}, indent=2))
    return out_path
