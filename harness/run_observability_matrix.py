from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from harness.coverage_matrix import write_coverage_complementarity
from harness.degradation import write_degradation_curves
from harness.evaluation_manifest import write_evaluation_manifest
from harness.matrix_generator import write_defense_matrix
from harness.run_report import write_run_report
from defenses.registry import DEFENSE_NAMES
from harness.multi_turn_runner import run_matrix


REPO_ROOT = Path(__file__).resolve().parents[1]


def _default_model_for_provider(provider: str) -> str:
    """Env-driven defaults per provider so OPENAI_API_KEY runs never send a Claude model id."""
    p = (provider or "anthropic").strip().lower()
    if p == "openai":
        return os.environ.get("OPENAI_MODEL", "gpt-4.1")
    if p == "together":
        return os.environ.get(
            "TOGETHER_MODEL",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        )
    return os.environ.get(
        "ANTHROPIC_MODEL",
        os.environ.get("FRONTIER_MODEL", "claude-sonnet-4-6"),
    )


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--scenarios",
        default=str(REPO_ROOT / "scenarios" / "scenarios.json"),
        help="Path to scenario catalog JSON",
    )
    ap.add_argument(
        "--defenses",
        default=",".join(DEFENSE_NAMES),
        help="Comma-separated defenses",
    )
    ap.add_argument(
        "--out",
        default=str(REPO_ROOT / "results" / "observability" / time.strftime("%Y%m%d-%H%M%S")),
    )
    ap.add_argument("--provider", default=os.environ.get("PROVIDER", "anthropic"))
    ap.add_argument(
        "--model",
        default=None,
        help="Model id for the provider. If omitted: OPENAI_MODEL or gpt-4.1 (openai); "
        "TOGETHER_MODEL or Llama-3.3-70B (together); ANTHROPIC_MODEL or FRONTIER_MODEL or "
        "claude-sonnet-4-6 (anthropic).",
    )
    ap.add_argument(
        "--k",
        type=int,
        default=int(os.environ.get("K", "1")),
        help="Repeats per scenario×defense×run_type. RESEARCH_PLAN.md / paper target: k=10 (set K=10 or OBS_K=10).",
    )
    ap.add_argument(
        "--axes",
        default=os.environ.get("OBS_AXES", ""),
        help="Comma-separated attack axes to include (e.g. D or A,B). Empty = all.",
    )
    ap.add_argument("--live-llm", action="store_true")
    ap.add_argument(
        "--orchestrator",
        default="minimal",
        choices=["minimal", "langgraph"],
        help="Orchestrator backend: 'minimal' (default hand-rolled ReAct) or 'langgraph'.",
    )
    ap.add_argument(
        "--skip-live-prompt-validation",
        action="store_true",
        help="With --live-llm, skip checks that every turn has a realistic user_prompt (debug / legacy only).",
    )
    ap.add_argument("--cache-dir", default=os.environ.get("LLM_CACHE_DIR"))
    args = ap.parse_args()

    model = args.model if args.model else _default_model_for_provider(args.provider)

    defenses = [d for d in args.defenses.split(",") if d]
    axes_raw = [a.strip().upper() for a in args.axes.split(",") if a.strip()]
    axes_filter: frozenset[str] | None = frozenset(axes_raw) if axes_raw else None
    out_root = Path(args.out)
    skip_prompt_check = bool(args.skip_live_prompt_validation) or os.environ.get(
        "SKIP_LIVE_PROMPT_VALIDATION", ""
    ).strip().lower() in ("1", "true", "yes")
    rows = run_matrix(
        scenarios_path=Path(args.scenarios),
        out_root=out_root,
        defenses=defenses,
        model=model,
        provider=args.provider,
        k=args.k,
        live_llm=bool(args.live_llm),
        cache_dir=args.cache_dir,
        axes=axes_filter,
        skip_live_prompt_validation=skip_prompt_check,
        orchestrator=args.orchestrator,
    )
    summary_rows = [r.__dict__ for r in rows]
    matrix_path = write_defense_matrix(out_root, summary_rows)
    curves_path = write_degradation_curves(out_root, summary_rows)
    scenarios_path = Path(args.scenarios)
    coverage_path = write_coverage_complementarity(out_root, summary_rows, scenarios_path)
    manifest_path = write_evaluation_manifest(
        out_root,
        scenarios_path=scenarios_path,
        defenses=defenses,
        model=model,
        provider=args.provider,
        k=args.k,
        live_llm=bool(args.live_llm),
        axes=sorted(axes_raw) if axes_raw else None,
    )
    report_path = write_run_report(out_root, scenarios_path)
    print(
        json.dumps(
            {
                "out_root": str(out_root),
                "runs": len(rows),
                "successes": sum(1 for r in rows if r.success),
                "defense_matrix": str(matrix_path),
                "degradation_curves": str(curves_path),
                "coverage_complementarity": str(coverage_path),
                "evaluation_manifest": str(manifest_path),
                "run_report": str(report_path),
                "provider": args.provider,
                "model": model,
                "orchestrator": args.orchestrator,
                "k": args.k,
                "live_llm": bool(args.live_llm),
                "axes": sorted(axes_raw) if axes_raw else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()
