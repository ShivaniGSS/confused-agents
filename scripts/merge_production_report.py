from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _iter_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def merge_campaign(campaign_dir: Path) -> dict[str, Any]:
    manifest = _iter_manifest(campaign_dir / "campaign_manifest.jsonl")
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in manifest:
        by_stage[str(row.get("stage", "unknown"))].append(row)

    summary: dict[str, Any] = {
        "campaign_dir": str(campaign_dir),
        "stage_counts": {
            stage: {
                "total": len(rows),
                "ok": sum(1 for r in rows if bool(r.get("ok"))),
                "failed": sum(1 for r in rows if not bool(r.get("ok"))),
            }
            for stage, rows in by_stage.items()
        },
        "observability": {},
        "externals": {},
    }

    obs_rows = by_stage.get("observability", [])
    obs_agg: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"n": 0.0, "attack_success_rate": 0.0, "detection_rate": 0.0, "false_positive_rate": 0.0}
    )
    eval_parents: dict[str, dict[str, Any]] = {}
    for row in obs_rows:
        if not row.get("ok"):
            continue
        matrix_path = Path(str(row.get("defense_matrix", "")))
        matrix_payload = _read_json(matrix_path)
        if not matrix_payload:
            continue
        provider = str(row.get("provider", "unknown"))
        model = str(row.get("model", "unknown"))
        for cell in matrix_payload.get("matrix", []):
            key = (provider, model)
            obs_agg[key]["n"] += 1.0
            obs_agg[key]["attack_success_rate"] += float(cell.get("attack_success_rate", 0.0))
            obs_agg[key]["detection_rate"] += float(cell.get("detection_rate", 0.0))
            obs_agg[key]["false_positive_rate"] += float(cell.get("false_positive_rate", 0.0))
        parent = str(matrix_path.parent)
        if parent not in eval_parents:
            eval_parents[parent] = {
                "out_dir": parent,
                "evaluation_manifest": _read_json(matrix_path.parent / "evaluation_manifest.json"),
                "coverage_complementarity": _read_json(matrix_path.parent / "coverage_complementarity.json"),
            }

    summary["observability"]["evaluation_artifacts"] = list(eval_parents.values())

    summary["observability"]["model_rollup"] = []
    for (provider, model), vals in sorted(obs_agg.items()):
        n = vals["n"] or 1.0
        summary["observability"]["model_rollup"].append(
            {
                "provider": provider,
                "model": model,
                "cells_aggregated": int(vals["n"]),
                "mean_attack_success_rate": vals["attack_success_rate"] / n,
                "mean_detection_rate": vals["detection_rate"] / n,
                "mean_false_positive_rate": vals["false_positive_rate"] / n,
            }
        )

    for ext_stage in ("agentdojo", "camel", "fides", "internal"):
        rows = by_stage.get(ext_stage, [])
        summary["externals"][ext_stage] = {
            "total": len(rows),
            "ok": sum(1 for r in rows if bool(r.get("ok"))),
            "failed": sum(1 for r in rows if not bool(r.get("ok"))),
            "artifacts": [str(r.get("artifact", "")) for r in rows if r.get("artifact")],
        }

    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign-dir", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    campaign_dir = Path(args.campaign_dir)
    payload = merge_campaign(campaign_dir)
    out_path = Path(args.out) if args.out else campaign_dir / "unified_report.json"
    out_path.write_text(json.dumps(payload, indent=2))
    print(json.dumps({"out": str(out_path)}, indent=2))


if __name__ == "__main__":
    main()
