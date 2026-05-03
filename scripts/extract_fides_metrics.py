#!/usr/bin/env python3
"""Extract lightweight case-study metrics from executed FIDES notebooks.

This parser is intentionally heuristic and text-driven: it scans notebook cell
outputs for signal phrases and computes per-run + aggregate counts. It is
useful for repeatability checks and trend tracking across repeated executions.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_PATTERNS: dict[str, str] = {
    "attack_success_true": r"attack[_ ]?success[^a-zA-Z0-9]*[:=][^a-zA-Z0-9]*true",
    "attack_success_false": r"attack[_ ]?success[^a-zA-Z0-9]*[:=][^a-zA-Z0-9]*false",
    "blocked": r"\b(blocked|deny|denied|rejected)\b",
    "allowed": r"\b(allowed|permit|permitted|accepted)\b",
    "error": r"\b(traceback|exception|error)\b",
}


def _cell_output_text(cell: dict[str, Any]) -> str:
    text_chunks: list[str] = []
    for out in cell.get("outputs", []):
        if "text" in out:
            text = out["text"]
            if isinstance(text, list):
                text_chunks.extend(str(x) for x in text)
            else:
                text_chunks.append(str(text))
        data = out.get("data", {})
        for k in ("text/plain", "text/markdown"):
            if k in data:
                v = data[k]
                if isinstance(v, list):
                    text_chunks.extend(str(x) for x in v)
                else:
                    text_chunks.append(str(v))
        if "ename" in out or "evalue" in out:
            text_chunks.append(str(out.get("ename", "")))
            text_chunks.append(str(out.get("evalue", "")))
    return "\n".join(text_chunks)


def extract_one(path: Path, compiled: dict[str, re.Pattern[str]]) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    cells = payload.get("cells", [])
    merged = []
    error_cells = 0
    for c in cells:
        if c.get("cell_type") != "code":
            continue
        txt = _cell_output_text(c)
        if txt:
            merged.append(txt)
        if any("ename" in out for out in c.get("outputs", [])):
            error_cells += 1
    corpus = "\n".join(merged).lower()
    counts = {name: len(rx.findall(corpus)) for name, rx in compiled.items()}
    return {
        "file": str(path),
        "n_code_cells": sum(1 for c in cells if c.get("cell_type") == "code"),
        "n_cells_with_output": sum(
            1
            for c in cells
            if c.get("cell_type") == "code" and bool(_cell_output_text(c).strip())
        ),
        "n_error_cells": error_cells,
        "metrics": counts,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", required=True, help="Directory containing executed .ipynb runs")
    ap.add_argument("--glob", default="**/*.ipynb", help="Notebook glob under runs-root")
    ap.add_argument("--out", required=True, help="Output JSON path")
    args = ap.parse_args()

    runs_root = Path(args.runs_root).resolve()
    notebooks = sorted(runs_root.glob(args.glob))
    compiled = {k: re.compile(v, re.IGNORECASE) for k, v in DEFAULT_PATTERNS.items()}

    rows = [extract_one(nb, compiled) for nb in notebooks]
    total = Counter()
    total_errors = 0
    for r in rows:
        total_errors += r["n_error_cells"]
        total.update(r["metrics"])

    summary = {
        "runs_root": str(runs_root),
        "n_runs": len(rows),
        "aggregate_metrics": dict(total),
        "aggregate_error_cells": total_errors,
        "patterns": DEFAULT_PATTERNS,
        "rows": rows,
    }

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"out": str(out), "n_runs": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
