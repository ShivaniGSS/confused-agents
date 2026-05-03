#!/usr/bin/env bash
set -euo pipefail

# Repeated execution harness for Microsoft FIDES Tutorial.ipynb plus metric extraction.
#
# Usage:
#   scripts/run_fides_case_study.sh --fides-root /path/to/fides
#
# Optional env:
#   N_RUNS=5
#   OUT_ROOT=results/external_fides_case_study
#   NOTEBOOK=Tutorial.ipynb
#   PYTHON_BIN=python3

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.openai.com,api.anthropic.com,api.together.xyz}"

FIDES_ROOT=""
N_RUNS="${N_RUNS:-5}"
OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/results/external_fides_case_study}"
NOTEBOOK="${NOTEBOOK:-Tutorial.ipynb}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fides-root)
      FIDES_ROOT="$2"
      shift 2
      ;;
    --n-runs)
      N_RUNS="$2"
      shift 2
      ;;
    --out-root)
      OUT_ROOT="$2"
      shift 2
      ;;
    --notebook)
      NOTEBOOK="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$FIDES_ROOT" ]]; then
  echo "Missing required --fides-root /path/to/fides" >&2
  exit 2
fi

if [[ ! -f "$FIDES_ROOT/$NOTEBOOK" ]]; then
  echo "Notebook not found: $FIDES_ROOT/$NOTEBOOK" >&2
  exit 2
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUT_ROOT/$STAMP"
mkdir -p "$RUN_DIR/runs"

echo "==> FIDES root: $FIDES_ROOT"
echo "==> notebook: $NOTEBOOK"
echo "==> runs: $N_RUNS"
echo "==> output: $RUN_DIR"

for ((i=1; i<=N_RUNS; i++)); do
  RUN_ID="$(printf "run_%03d" "$i")"
  DEST="$RUN_DIR/runs/$RUN_ID"
  mkdir -p "$DEST"
  echo "==> [$RUN_ID] executing notebook"
  (
    cd "$FIDES_ROOT"
    jupyter nbconvert \
      --to notebook \
      --execute "$NOTEBOOK" \
      --output "$RUN_ID.executed.ipynb" \
      --output-dir "$DEST" \
      >"$DEST/stdout.log" 2>"$DEST/stderr.log"
  )
  echo "==> [$RUN_ID] done"
done

echo "==> extracting aggregate metrics"
"$PYTHON_BIN" "$REPO_ROOT/scripts/extract_fides_metrics.py" \
  --runs-root "$RUN_DIR/runs" \
  --glob "**/*.executed.ipynb" \
  --out "$RUN_DIR/metrics_summary.json"

cat >"$RUN_DIR/run_meta.txt" <<EOF
fides_root=$FIDES_ROOT
notebook=$NOTEBOOK
n_runs=$N_RUNS
output=$RUN_DIR
timestamp=$STAMP
EOF

echo "==> done. outputs in: $RUN_DIR"
