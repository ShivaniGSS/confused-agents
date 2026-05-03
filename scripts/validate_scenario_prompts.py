#!/usr/bin/env python3
"""Validate scenarios.json: every attack and benign turn must have user_prompt (live-LLM contract).

Usage (from repo root):
  python3 scripts/validate_scenario_prompts.py
  python3 scripts/validate_scenario_prompts.py --scenarios path/to/scenarios.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.scenario_prompt_validation import validate_catalog_live_user_prompts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--scenarios",
        type=Path,
        default=ROOT / "scenarios" / "scenarios.json",
        help="Path to scenarios catalog JSON",
    )
    args = ap.parse_args()
    payload = json.loads(args.scenarios.read_text())
    errs = validate_catalog_live_user_prompts(payload)
    if errs:
        print("Scenario user_prompt validation failed:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    n = len(payload.get("scenarios", []))
    print(f"OK: {n} scenarios, all turns have user_prompt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
