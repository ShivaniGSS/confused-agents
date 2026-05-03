from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

Z_95 = 1.959963984540054


def wilson_ci(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def fmt_rate(successes: int, n: int) -> str:
    if n == 0:
        return "—"
    r = successes / n
    lo, hi = wilson_ci(successes, n)
    return f"{r:.3f} [{lo:.2f}, {hi:.2f}] (n={n})"


ROOT = Path(__file__).resolve().parent.parent / "results"

CANONICAL_DIRS: list[tuple[Path, str, str]] = [
    (ROOT / "production_campaign" / "gpt41_k10_20260429-162857" / "observability",
     "GPT-4.1", "A-H"),
    (ROOT / "sweep3_gpt41_ijkl_k10", "GPT-4.1", "I-L"),
    (ROOT / "ah_claude_k10", "Claude Sonnet 4.6", "A-H"),
    (ROOT / "sweep2_claude-sonnet-v2", "Claude Sonnet 4.6", "I-L (k=1)"),
    (ROOT / "ah_llama_k10", "Llama-3.3-70B", "A-H"),
    (ROOT / "sweep3_llama_ijkl_k10", "Llama-3.3-70B", "I-L"),
]


def load_summary_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
    for fpath in path.rglob("summary.jsonl"):
        for line in fpath.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def group_rows(rows: list[dict]) -> dict:
    groups: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        groups[r["scenario_id"]][r["defense"]][r["run_type"]].append(r)
    return groups


def compute_asr(attack_rows: list[dict]) -> tuple[int, int]:
    successes = sum(1 for r in attack_rows if r.get("success"))
    return successes, len(attack_rows)


def compute_dr(attack_rows: list[dict]) -> tuple[int, int]:
    blocked = sum(1 for r in attack_rows if r.get("blocked"))
    return blocked, len(attack_rows)


def compute_fpr(benign_rows: list[dict]) -> tuple[int, int]:
    fps = sum(1 for r in benign_rows if r.get("blocked") or r.get("success"))
    return fps, len(benign_rows)


DEFENSES_ORDER = [
    "none", "spotlighting", "integrity_only", "camel_style",
    "capguard", "trajectory_monitor", "full_stack",
]


def print_table(label: str, rows: list[dict]) -> None:
    groups = group_rows(rows)
    scenarios = sorted(groups.keys())

    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"  Total rows: {len(rows)}")
    print(f"{'='*80}")

    for scenario_id in scenarios:
        defenses = groups[scenario_id]
        print(f"\n  Scenario: {scenario_id}")
        print(f"  {'Defense':<22} {'ASR (Wilson 95% CI)':<35} {'DR (Wilson 95% CI)':<35} {'FPR (Wilson 95% CI)':<35}")
        print(f"  {'-'*22} {'-'*35} {'-'*35} {'-'*35}")

        for defense in DEFENSES_ORDER:
            if defense not in defenses:
                continue
            attack_rows = defenses[defense].get("attack", [])
            benign_rows = defenses[defense].get("benign", [])

            asr_s, asr_n = compute_asr(attack_rows)
            dr_s, dr_n = compute_dr(attack_rows)
            fpr_s, fpr_n = compute_fpr(benign_rows)

            asr_str = fmt_rate(asr_s, asr_n) if asr_n else "—"
            dr_str = fmt_rate(dr_s, dr_n) if dr_n else "—"
            fpr_str = fmt_rate(fpr_s, fpr_n) if fpr_n else "—"

            print(f"  {defense:<22} {asr_str:<35} {dr_str:<35} {fpr_str:<35}")


def print_summary_by_axis(label: str, rows: list[dict]) -> None:
    by_axis: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        axis = r.get("axis", "?")
        defense = r.get("defense", "?")
        run_type = r.get("run_type", "?")
        by_axis[axis][defense][run_type].append(r)

    print(f"\n{'='*80}")
    print(f"  {label} — axis rollup")
    print(f"{'='*80}")
    print(f"  {'Axis':<5} {'Defense':<22} {'ASR':<8} {'DR':<8} {'FPR':<8} {'Executions'}")
    print(f"  {'-'*5} {'-'*22} {'-'*8} {'-'*8} {'-'*8} {'-'*20}")

    for axis in sorted(by_axis):
        for defense in DEFENSES_ORDER:
            if defense not in by_axis[axis]:
                continue
            atk = by_axis[axis][defense].get("attack", [])
            ben = by_axis[axis][defense].get("benign", [])

            asr_s, asr_n = compute_asr(atk)
            dr_s, dr_n = compute_dr(atk)
            fpr_s, fpr_n = compute_fpr(ben)

            n_exec = sum(1 for r in atk if r.get("model_safety_outcome") == "executed")

            asr = f"{asr_s/asr_n:.3f}" if asr_n else "—"
            dr = f"{dr_s/dr_n:.3f}" if dr_n else "—"
            fpr = f"{fpr_s/fpr_n:.3f}" if fpr_n else "—"
            print(f"  {axis:<5} {defense:<22} {asr:<8} {dr:<8} {fpr:<8} {n_exec}/{asr_n} executed")


def print_model_comparison(all_results: list[tuple[str, str, list[dict]]]) -> None:
    print(f"\n{'='*80}")
    print("  Cross-model ASR comparison (canonical k=10 runs)")
    print(f"{'='*80}")

    scenario_sets: dict[str, dict[str, list]] = defaultdict(dict)
    for label, axes, rows in all_results:
        for r in rows:
            if r.get("defense") == "none" and r.get("run_type") == "attack":
                sid = r["scenario_id"]
                scenario_sets[sid].setdefault(label, []).append(r)

    print(f"\n  {'Scenario':<50}", end="")
    models = [label for label, _, _ in all_results]
    for m in models:
        print(f"  {m[:18]:<20}", end="")
    print()
    print(f"  {'-'*50}", end="")
    for _ in models:
        print(f"  {'-'*20}", end="")
    print()

    for sid in sorted(scenario_sets):
        print(f"  {sid:<50}", end="")
        for label, _, _ in all_results:
            rows_m = scenario_sets[sid].get(label, [])
            if not rows_m:
                print(f"  {'—':<20}", end="")
            else:
                s, n = compute_asr(rows_m)
                print(f"  {s}/{n} ({s/n:.2f}){'':>8}", end="")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce Table 2: ASR, DR, FPR with Wilson 95% CIs."
    )
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Write tables to this directory as .txt files")
    parser.add_argument("--axis-rollup", action="store_true", default=False,
                        help="Print axis-level rollups instead of per-scenario tables")
    args = parser.parse_args()

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    for result_dir, model_label, axes_label in CANONICAL_DIRS:
        if not result_dir.exists():
            print(f"[SKIP] {result_dir} not found", file=sys.stderr)
            continue
        rows = load_summary_jsonl(result_dir)
        if not rows:
            print(f"[SKIP] {result_dir} — no rows found", file=sys.stderr)
            continue
        label = f"{model_label} | Axes {axes_label}"
        all_results.append((label, axes_label, rows))

        if args.axis_rollup:
            print_summary_by_axis(label, rows)
        else:
            print_table(label, rows)

    print_model_comparison(all_results)

    print("\n\nWilson CI note: all CIs are 95% two-sided Wilson score intervals.")
    print("See harness/metrics.py for the closed-form implementation.")


if __name__ == "__main__":
    main()
