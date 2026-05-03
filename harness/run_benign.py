"""Benign workload runner (CLAUDE.md Section 9).

Runs every item in `attacks/benign/` k times against each
(orchestrator, capguard) configuration, and counts blocked LEGITIMATE
invocations as false positives.

A benign item is structurally identical to an attack fixture but its
success.json declares a *negative* outcome: any tool call CapGuard
blocks counts as a false positive. The presence of an `expected_calls`
list in success.json is read as the canonical legitimate behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.metrics import Proportion
from harness.run_attack import RunOutcome, load_attack, run_k
from orchestrators._llm import make_client


REPO_ROOT = Path(__file__).resolve().parents[1]
BENIGN_ROOT = REPO_ROOT / "attacks" / "benign"
DEFAULT_RESULTS = REPO_ROOT / "results"


@dataclass
class BenignCellResult:
    item_id: str
    orchestrator: str
    capguard: str
    k: int
    blocked_runs: int
    fpr: float
    ci_lo: float
    ci_hi: float


def _block_count(workdir: Path) -> int:
    """Count CapGuard 'block' decisions in the per-run agent log."""
    log = workdir / "logs" / "agent.jsonl"
    if not log.exists():
        return 0
    n = 0
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "capguard_decision" and rec.get("decision") == "block":
            n += 1
    return n


def discover_benign() -> list[Path]:
    if not BENIGN_ROOT.is_dir():
        return []
    return [p for p in sorted(BENIGN_ROOT.iterdir()) if (p / "fixture.json").exists()]


def run_benign(
    *,
    orchestrators: list[str],
    capguard_modes: list[str],
    make_client_fn,
    model: str,
    k: int,
    out_root: Path,
    cache_dir: str | None = None,
) -> list[BenignCellResult]:
    cells: list[BenignCellResult] = []
    out_root.mkdir(parents=True, exist_ok=True)
    items = discover_benign()
    for item in items:
        for orch in orchestrators:
            for cg in capguard_modes:
                cell_dir = out_root / item.name / f"{orch}__cg-{cg}"
                attack = load_attack(item)
                defense_mode = "capguard_full" if cg == "on" else "none"
                outcomes: list[RunOutcome] = run_k(
                    attack,
                    make_client_fn=make_client_fn,
                    model=model,
                    k=k,
                    base_dir=cell_dir,
                    defense=defense_mode,
                    cache_dir=cache_dir,
                )
                blocked = sum(
                    1 for i, _ in enumerate(outcomes)
                    if _block_count(cell_dir / f"run_{i:03d}") > 0
                )
                p = Proportion(successes=blocked, n=len(outcomes))
                lo, hi = p.wilson_ci()
                cells.append(BenignCellResult(
                    item_id=item.name, orchestrator=orch, capguard=cg,
                    k=len(outcomes), blocked_runs=blocked, fpr=p.rate,
                    ci_lo=lo, ci_hi=hi,
                ))
    summary_path = out_root / "benign_summary.jsonl"
    with summary_path.open("w") as f:
        for c in cells:
            f.write(json.dumps(asdict(c), sort_keys=True) + "\n")
    return cells


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orchestrators", default="minimal")
    ap.add_argument("--capguard", default="on")
    ap.add_argument("--provider", default=os.environ.get("PROVIDER", "anthropic"))
    ap.add_argument("--model", default=os.environ.get("FRONTIER_MODEL", "claude-sonnet-4-6"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_root = Path(args.out) if args.out else (
        DEFAULT_RESULTS / "benign" / time.strftime("%Y%m%d-%H%M%S")
    )
    cache_dir = os.environ.get("LLM_CACHE_DIR", str(DEFAULT_RESULTS / "llm_cache"))

    def factory():
        return make_client(args.provider)

    cells = run_benign(
        orchestrators=[s for s in args.orchestrators.split(",") if s],
        capguard_modes=[s for s in args.capguard.split(",") if s],
        make_client_fn=factory,
        model=args.model,
        k=args.k,
        out_root=out_root,
        cache_dir=cache_dir,
    )
    print(json.dumps({
        "out_root": str(out_root),
        "cells": [asdict(c) for c in cells],
    }, indent=2))


if __name__ == "__main__":
    _main()
