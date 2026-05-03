#!/usr/bin/env bash
set -euo pipefail

# Wrapper to run CAMEL benchmark example scripts with consistent outputs.
#
# Usage:
#   scripts/run_camel_benchmarks.sh --camel-root /path/to/camel
#
# Optional env:
#   OUT_ROOT=results/external_camel
#   RUN_APIBENCH=1 RUN_APIBANK=1 RUN_GAIA=0
#
# Notes:
# - This wrapper expects a checked-out CAMEL repo with benchmark examples under
#   examples/benchmarks/.
# - GAIA requires Docker runtime setup in CAMEL (see comments in gaia.py).

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Keep benchmark calls resilient to host proxy misconfiguration.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.openai.com,api.anthropic.com,api.together.xyz}"

CAMEL_ROOT=""
OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/results/external_camel}"
RUN_APIBENCH="${RUN_APIBENCH:-1}"
RUN_APIBANK="${RUN_APIBANK:-1}"
RUN_GAIA="${RUN_GAIA:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --camel-root)
      CAMEL_ROOT="$2"
      shift 2
      ;;
    --out-root)
      OUT_ROOT="$2"
      shift 2
      ;;
    --run-gaia)
      RUN_GAIA="$2"
      shift 2
      ;;
    --run-apibench)
      RUN_APIBENCH="$2"
      shift 2
      ;;
    --run-apibank)
      RUN_APIBANK="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$CAMEL_ROOT" ]]; then
  echo "Missing required --camel-root /path/to/camel" >&2
  exit 2
fi

if [[ ! -d "$CAMEL_ROOT/examples/benchmarks" ]]; then
  echo "Invalid CAMEL root: benchmark examples not found at $CAMEL_ROOT/examples/benchmarks" >&2
  exit 2
fi

mkdir -p "$OUT_ROOT"
STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUT_ROOT/$STAMP"
mkdir -p "$RUN_DIR"

echo "==> CAMEL root: $CAMEL_ROOT"
echo "==> output dir: $RUN_DIR"

run_one() {
  local name="$1"
  local script="$2"
  local out_dir="$RUN_DIR/$name"
  mkdir -p "$out_dir"
  echo "==> [$name] running $script"
  (
    cd "$CAMEL_ROOT"
    python "$script" >"$out_dir/stdout.log" 2>"$out_dir/stderr.log"
  )
  echo "==> [$name] done (logs: $out_dir)"
}

if [[ "$RUN_APIBENCH" == "1" ]]; then
  run_one "apibench" "examples/benchmarks/apibench.py"
fi

if [[ "$RUN_APIBANK" == "1" ]]; then
  run_one "apibank" "examples/benchmarks/apibank.py"
fi

if [[ "$RUN_GAIA" == "1" ]]; then
  run_one "gaia" "examples/benchmarks/gaia.py"
else
  echo "==> [gaia] skipped (set RUN_GAIA=1 or --run-gaia 1 to enable)"
fi

cat >"$RUN_DIR/run_meta.txt" <<EOF
camel_root=$CAMEL_ROOT
out_root=$RUN_DIR
run_apibench=$RUN_APIBENCH
run_apibank=$RUN_APIBANK
run_gaia=$RUN_GAIA
timestamp=$STAMP
EOF

echo "==> done. CAMEL benchmark outputs in: $RUN_DIR"
