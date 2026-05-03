# FIDES Case-Study Runbook

This runbook treats Microsoft FIDES as a repeatable case-study track rather than a benchmark CLI.

## What this does

- Re-runs `Tutorial.ipynb` multiple times
- Saves per-run executed notebooks and logs
- Extracts lightweight text metrics into one aggregate JSON summary

## Prerequisites

- Local clone of Microsoft FIDES repo (`https://github.com/microsoft/fides`)
- Notebook dependencies installed in your environment
- Endpoint auth configured in FIDES `.env` (per their README)

## Command

```bash
cd $(pwd)
scripts/run_fides_case_study.sh --fides-root /absolute/path/to/fides
```

Optional knobs:

- `N_RUNS=10` for more repetitions
- `OUT_ROOT=results/external_fides_case_study`
- `NOTEBOOK=Tutorial.ipynb`

Example:

```bash
N_RUNS=10 OUT_ROOT=results/external_fides_case_study \
scripts/run_fides_case_study.sh --fides-root ../fides
```

## Outputs

- `results/external_fides_case_study/<timestamp>/runs/run_XXX/*.executed.ipynb`
- `results/external_fides_case_study/<timestamp>/runs/run_XXX/stdout.log`
- `results/external_fides_case_study/<timestamp>/runs/run_XXX/stderr.log`
- `results/external_fides_case_study/<timestamp>/metrics_summary.json`

## Interpreting `metrics_summary.json`

- `n_runs`: total executed runs found
- `aggregate_error_cells`: total notebook code cells that raised errors
- `aggregate_metrics`: regex-based signal counts across all runs
  - `attack_success_true`
  - `attack_success_false`
  - `blocked`
  - `allowed`
  - `error`

This is a pragmatic consistency tracker; for publication-grade scoring, add task-level structured logging directly in the notebook.
