"""Full-corpus runner with rebooted defense set.

Defense modes:
  none, baseline_combined, capguard_full
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.metrics import Proportion
from harness.run_attack import DEFENSE_MODES, RunOutcome, load_attack, run_k
from orchestrators._llm import ScriptedClient, ScriptedStep, make_client


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "attacks" / "fixtures"
DEFAULT_RESULTS = REPO_ROOT / "results"


@dataclass
class CellResult:
    scenario: str
    attack_id: str
    orchestrator: str
    defense: str  # one of DEFENSE_MODES
    k: int
    successes: int
    asr: float
    ci_lo: float
    ci_hi: float


def discover_attacks(scenarios: list[str]) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for s in scenarios:
        sdir = FIXTURE_ROOT / s
        if not sdir.is_dir():
            raise FileNotFoundError(sdir)
        for attack_dir in sorted(sdir.iterdir()):
            if not attack_dir.is_dir():
                continue
            if not (attack_dir / "fixture.json").exists():
                continue
            out.append((s, attack_dir))
    return out


def run_corpus(
    *,
    scenarios: list[str],
    orchestrators: list[str],
    defense_modes: list[str],
    make_client_fn,
    model: str,
    k: int,
    out_root: Path,
    cache_dir: str | None = None,
) -> list[CellResult]:
    for dm in defense_modes:
        if dm not in DEFENSE_MODES:
            raise ValueError(f"unknown defense mode: {dm!r}")
    cells: list[CellResult] = []
    attacks = discover_attacks(scenarios)
    out_root.mkdir(parents=True, exist_ok=True)
    for scenario, adir in attacks:
        for orch in orchestrators:
            for dm in defense_modes:
                cell_dir = out_root / scenario / adir.name / f"{orch}__def-{dm}"
                attack = load_attack(adir)
                outcomes: list[RunOutcome] = run_k(
                    attack,
                    make_client_fn=make_client_fn,
                    model=model,
                    k=k,
                    base_dir=cell_dir,
                    defense=dm,
                    cache_dir=cache_dir,
                )
                successes = sum(1 for o in outcomes if o.attack_success)
                p = Proportion(successes=successes, n=len(outcomes))
                lo, hi = p.wilson_ci()
                cells.append(CellResult(
                    scenario=scenario, attack_id=adir.name, orchestrator=orch,
                    defense=dm, k=len(outcomes), successes=successes,
                    asr=p.rate, ci_lo=lo, ci_hi=hi,
                ))
    summary_path = out_root / "corpus_summary.jsonl"
    with summary_path.open("w") as f:
        for c in cells:
            f.write(json.dumps(asdict(c), sort_keys=True) + "\n")
    return cells


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=(
        "scenario_a_calendar,scenario_b_docs,scenario_c_multitenant,scenario_d_purpose"
    ))
    ap.add_argument("--orchestrators", default="minimal")
    ap.add_argument("--defenses", default="none,baseline_combined,capguard_full")
    ap.add_argument("--provider", default=os.environ.get("PROVIDER", "anthropic"))
    ap.add_argument("--model", default=os.environ.get("FRONTIER_MODEL", "claude-sonnet-4-6"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_root = Path(args.out) if args.out else (
        DEFAULT_RESULTS / "corpus" / time.strftime("%Y%m%d-%H%M%S")
    )
    cache_dir = os.environ.get("LLM_CACHE_DIR", str(DEFAULT_RESULTS / "llm_cache"))

    def factory():
        return make_client(args.provider)

    cells = run_corpus(
        scenarios=[s for s in args.scenarios.split(",") if s],
        orchestrators=[s for s in args.orchestrators.split(",") if s],
        defense_modes=[s for s in args.defenses.split(",") if s],
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
