from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_summary_rows(out_root: Path) -> list[dict[str, Any]]:
    p = out_root / "summary.jsonl"
    rows: list[dict[str, Any]] = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _scenario_labels(scenarios_path: Path) -> dict[str, str]:
    payload = json.loads(scenarios_path.read_text())
    out: dict[str, str] = {}
    for s in payload.get("scenarios", []):
        sid = str(s.get("id", ""))
        if not sid:
            continue
        ap = s.get("axis_param") or {}
        pv = ap.get("value", "")
        pn = ap.get("name", "")
        extra = f"{pn}={pv}" if pn else ""
        out[sid] = extra
    return out


def write_run_report(out_root: Path, scenarios_path: Path) -> Path:
    """Emit scenario-first `RUN_REPORT.md` for an observability run directory."""
    rows = _load_summary_rows(out_root)
    labels = _scenario_labels(scenarios_path)
    matrix_path = out_root / "defense_landscape_matrix.json"
    manifest_path = out_root / "evaluation_manifest.json"
    matrix_cells: list[dict[str, Any]] = []
    if matrix_path.exists():
        matrix_cells = json.loads(matrix_path.read_text()).get("matrix", [])
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    run_meta = manifest.get("run", {})
    axes = run_meta.get("axes_filter")
    k = run_meta.get("k")
    model = run_meta.get("model")
    provider = run_meta.get("provider")

    by_sc_def: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"attack": [], "benign": []}
    )
    for r in rows:
        key = (str(r.get("scenario_id", "")), str(r.get("defense", "")))
        rt = str(r.get("run_type", ""))
        if rt in ("attack", "benign"):
            by_sc_def[key][rt].append(r)

    scenario_ids = sorted({str(r.get("scenario_id", "")) for r in rows if r.get("scenario_id")})
    defenses = []
    seen: set[str] = set()
    for r in rows:
        d = str(r.get("defense", ""))
        if d and d not in seen:
            seen.add(d)
            defenses.append(d)

    lines: list[str] = []
    lines.append(f"# Observability run report — `{out_root.name}`")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Output directory | `{out_root}` |")
    if provider:
        lines.append(f"| Provider / model | {provider} / `{model}` |")
    if k is not None:
        lines.append(f"| Repeats `k` | {k} |")
    if axes is not None:
        lines.append(f"| Axes filter | {', '.join(axes)} |")
    lines.append("")
    lines.append("## How to read this report")
    lines.append("")
    lines.append(
        "1. **Per-scenario tables (below) are primary.** Axis rollups aggregate away elicitation "
        "differences between scenarios in the same letter bucket."
    )
    lines.append(
        "2. **`detection_rate` in `defense_landscape_matrix.json` uses all attack rows.** When the "
        "model refuses or fails without executing tools, use **`detection_rate_given_attack_executed`** "
        "(Wilson CI in the same cell) — it is `null` when no attack row had `model_safety_outcome=executed`."
    )
    lines.append(
        "3. **Axis H** (`metric_decomposition` in `scenarios.json`): distinguish **injection/schema "
        "compliance** from **CapGuard routing** (subject binding on `gmail.send_message.to` local-part)."
    )
    lines.append(
        "4. **Trajectory monitor** at 0% detection is a **finding** about mismatch between this "
        "implementation’s drift signal and corpus violation patterns, not evidence that monitoring is "
        "irrelevant in general."
    )
    lines.append("")

    n_attack = sum(1 for r in rows if r.get("run_type") == "attack")
    n_benign = sum(1 for r in rows if r.get("run_type") == "benign")
    succ = sum(1 for r in rows if r.get("run_type") == "attack" and r.get("success"))
    lines.append("## Run scale")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| Total rows (`summary.jsonl`) | {len(rows)} |")
    lines.append(f"| Attack rows | {n_attack} |")
    lines.append(f"| Benign rows | {n_benign} |")
    if n_attack:
        lines.append(
            f"| Attack rows with executed violation (`success`) | {succ} ({100.0 * succ / n_attack:.1f}%) |"
        )
    lines.append("")

    lines.append("## Per-scenario breakdown (primary)")
    lines.append("")
    for sid in scenario_ids:
        ax = next((str(r.get("axis", "")) for r in rows if r.get("scenario_id") == sid), "")
        param = labels.get(sid, "")
        title = f"`{sid}`"
        if param:
            title += f" ({ax}, {param})"
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| defense | attack ASR | benign viol. | blocked attack | blocked benign |")
        lines.append("| --- | --- | --- | --- | --- |")
        for defn in defenses:
            atk = by_sc_def.get((sid, defn), {}).get("attack", [])
            ben = by_sc_def.get((sid, defn), {}).get("benign", [])
            asr = sum(1 for r in atk if r.get("success"))
            bviol = sum(1 for r in ben if r.get("success"))
            ablk = sum(1 for r in atk if int(r.get("detection_turn", -1)) >= 0)
            bblk = sum(1 for r in ben if int(r.get("detection_turn", -1)) >= 0)
            ta, tb = len(atk), len(ben)
            lines.append(
                f"| {defn} | {asr}/{ta} | {bviol}/{tb} | {ablk}/{ta} | {bblk}/{tb} |"
            )
        lines.append("")

    lines.append("## Defense landscape matrix (secondary / axis rollups)")
    lines.append("")
    lines.append("See `defense_landscape_matrix.json` for full numeric cells including ")
    lines.append("`detection_rate_given_attack_executed` and conditional Wilson intervals.")
    lines.append("")
    if matrix_cells:
        lines.append("| axis | defense | ASR | FPR | det (all attacks) | det (given executed) |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for c in sorted(matrix_cells, key=lambda x: (x.get("axis", ""), x.get("defense", ""))):
            ax = c.get("axis", "")
            d = c.get("defense", "")
            asr = c.get("attack_success_rate", 0.0)
            fpr = c.get("false_positive_rate", 0.0)
            det = c.get("detection_rate", 0.0)
            dge = c.get("detection_rate_given_attack_executed")
            dge_s = "—" if dge is None else f"{float(dge):.2f}"
            lines.append(f"| {ax} | {d} | {asr:.2f} | {fpr:.2f} | {det:.2f} | {dge_s} |")
        lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    lines.append("| File | Role |")
    lines.append("| --- | --- |")
    lines.append("| `summary.jsonl` | Per-run rows |")
    lines.append("| `defense_landscape_matrix.json` | Axis × defense metrics |")
    lines.append("| `degradation_curves.json` | Param-stratified curves |")
    lines.append("| `coverage_complementarity.json` | Axis semantics + matrix roll-up |")
    lines.append("| `evaluation_manifest.json` | Run metadata |")
    lines.append("")
    lines.append(
        f"*Auto-generated by `harness/run_report.py` for `{out_root.name}`.*"
    )

    out_path = out_root / "RUN_REPORT.md"
    out_path.write_text("\n".join(lines) + "\n")
    return out_path
