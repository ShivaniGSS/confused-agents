#!/usr/bin/env python3
"""Corpus audit for Phase 1 completion gates.

Reads fixture metadata from attacks/fixtures and (optionally) verifier reports
to summarize:
  - domain distribution
  - target tool distribution
  - injection-style diversity
  - duplicate risk (same target tool + injection style)
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FixtureRow:
    path: Path
    scenario: str
    attack_id: str
    target_tool: str
    injection_style: str
    domain: str


def _domain_for(path: Path, success_meta: dict[str, Any], fixture: dict[str, Any]) -> str:
    if "clinical" in path.as_posix() or str(success_meta.get("family", "")).lower().startswith("d"):
        subs = fixture.get("principals", {}).get("subjects")
        if isinstance(subs, list) and any(str(s).startswith("patient-") for s in subs):
            return "clinical"
        if isinstance(subs, list) and any(str(s).startswith("client-") for s in subs):
            return "financial"
    if "financial" in path.as_posix():
        return "financial"
    # Heuristic fallback by scenario family.
    scen = str(success_meta.get("scenario", ""))
    if "purpose" in scen:
        subs = fixture.get("principals", {}).get("subjects")
        if isinstance(subs, list) and any(str(s).startswith("client-") for s in subs):
            return "financial"
        return "clinical"
    return "operations"


def discover_fixtures(root: Path) -> list[FixtureRow]:
    rows: list[FixtureRow] = []
    for success in root.glob("**/success.json"):
        fx_dir = success.parent
        fixture_file = fx_dir / "fixture.json"
        if not fixture_file.exists():
            continue
        s = json.loads(success.read_text())
        f = json.loads(fixture_file.read_text())
        meta = s.get("metadata", {})
        rows.append(
            FixtureRow(
                path=fx_dir,
                scenario=str(meta.get("scenario", fx_dir.parent.name)),
                attack_id=str(meta.get("attack_id", fx_dir.name)),
                target_tool=str(meta.get("target_operation", "unknown")),
                injection_style=str(meta.get("injection_style", "unknown")),
                domain=_domain_for(fx_dir, meta, f),
            )
        )
    return sorted(rows, key=lambda r: (r.scenario, r.attack_id))


def _read_verified_only(report_root: Path) -> set[str]:
    keep: set[str] = set()
    if not report_root.exists():
        return keep
    for rp in report_root.glob("**/verification_report.json"):
        try:
            payload = json.loads(rp.read_text())
        except Exception:
            continue
        if bool(payload.get("verdict")):
            keep.add(str(Path(payload.get("fixture", "")).resolve()))
    return keep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-root", default="attacks/fixtures")
    ap.add_argument(
        "--verified-reports-root",
        default=None,
        help="If set, restrict audit to fixtures with verifier verdict=true in this tree.",
    )
    ap.add_argument("--out", default="results/corpus_audit.json")
    args = ap.parse_args()

    rows = discover_fixtures(Path(args.fixtures_root).resolve())
    if args.verified_reports_root:
        keep = _read_verified_only(Path(args.verified_reports_root).resolve())
        rows = [r for r in rows if str(r.path.resolve()) in keep]

    domain_counts = Counter(r.domain for r in rows)
    tool_counts = Counter(r.target_tool for r in rows)
    style_counts = Counter(r.injection_style for r in rows)
    pair_counts = Counter((r.target_tool, r.injection_style) for r in rows)
    duplicate_pairs = {
        f"{tool}||{style}": n
        for (tool, style), n in sorted(pair_counts.items())
        if n > 1
    }

    audit = {
        "n_fixtures": len(rows),
        "domains": domain_counts,
        "target_tools": tool_counts,
        "injection_styles": style_counts,
        "duplicate_tool_style_pairs": duplicate_pairs,
        "fixtures": [
            {
                "path": str(r.path),
                "scenario": r.scenario,
                "attack_id": r.attack_id,
                "domain": r.domain,
                "target_tool": r.target_tool,
                "injection_style": r.injection_style,
            }
            for r in rows
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"out": str(out), "n_fixtures": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
