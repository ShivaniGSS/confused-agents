#!/usr/bin/env bash
set -euo pipefail

# Top-level orchestrator for "true full run" across:
# 1) Internal harness (3 phases)
# 2) AgentDojo
# 3) CAMEL benchmarks
# 4) FIDES case-study
#
# Required:
#   --agentdojo-root /path/to/agentdojo
#   --camel-root /path/to/camel
#   --fides-root /path/to/fides
#
# Optional env:
#   OUT_ROOT=results/true_full_matrix
#   RUN_INTERNAL=1 RUN_AGENTDOJO=1 RUN_CAMEL=1 RUN_FIDES=1
#   K_VERIFY=4 K_CORPUS=10 MIN_SUCCESSES=2 N_FIDES_RUNS=5

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.openai.com,api.anthropic.com,api.together.xyz}"

AGENTDOJO_ROOT=""
CAMEL_ROOT=""
FIDES_ROOT=""

OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/results/true_full_matrix}"
RUN_INTERNAL="${RUN_INTERNAL:-1}"
RUN_AGENTDOJO="${RUN_AGENTDOJO:-1}"
RUN_CAMEL="${RUN_CAMEL:-1}"
RUN_FIDES="${RUN_FIDES:-1}"

K_VERIFY="${K_VERIFY:-4}"
K_CORPUS="${K_CORPUS:-10}"
MIN_SUCCESSES="${MIN_SUCCESSES:-2}"
N_FIDES_RUNS="${N_FIDES_RUNS:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agentdojo-root)
      AGENTDOJO_ROOT="$2"
      shift 2
      ;;
    --camel-root)
      CAMEL_ROOT="$2"
      shift 2
      ;;
    --fides-root)
      FIDES_ROOT="$2"
      shift 2
      ;;
    --out-root)
      OUT_ROOT="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUT_ROOT/$STAMP"
mkdir -p "$RUN_DIR"

echo "==> true full matrix run: $RUN_DIR"

if [[ "$RUN_INTERNAL" == "1" ]]; then
  echo "==> [internal] starting"
  K_VERIFY="$K_VERIFY" K_CORPUS="$K_CORPUS" MIN_SUCCESSES="$MIN_SUCCESSES" \
    OUT_ROOT="$RUN_DIR/internal" \
    bash "$REPO_ROOT/scripts/run_full_three_phases.sh" \
    >"$RUN_DIR/internal.stdout.log" 2>"$RUN_DIR/internal.stderr.log"
  echo "==> [internal] done"
else
  echo "==> [internal] skipped"
fi

if [[ "$RUN_AGENTDOJO" == "1" ]]; then
  if [[ -z "$AGENTDOJO_ROOT" ]]; then
    echo "==> [agentdojo] skipped (missing --agentdojo-root)"
  else
    echo "==> [agentdojo] starting"
    OUT_ROOT="$RUN_DIR/agentdojo" \
      bash "$REPO_ROOT/scripts/run_agentdojo_benchmarks.sh" \
      --agentdojo-root "$AGENTDOJO_ROOT" \
      >"$RUN_DIR/agentdojo.stdout.log" 2>"$RUN_DIR/agentdojo.stderr.log"
    echo "==> [agentdojo] done"
  fi
else
  echo "==> [agentdojo] skipped"
fi

if [[ "$RUN_CAMEL" == "1" ]]; then
  if [[ -z "$CAMEL_ROOT" ]]; then
    echo "==> [camel] skipped (missing --camel-root)"
  else
    echo "==> [camel] starting"
    OUT_ROOT="$RUN_DIR/camel" RUN_GAIA=1 \
      bash "$REPO_ROOT/scripts/run_camel_benchmarks.sh" \
      --camel-root "$CAMEL_ROOT" \
      >"$RUN_DIR/camel.stdout.log" 2>"$RUN_DIR/camel.stderr.log"
    echo "==> [camel] done"
  fi
else
  echo "==> [camel] skipped"
fi

if [[ "$RUN_FIDES" == "1" ]]; then
  if [[ -z "$FIDES_ROOT" ]]; then
    echo "==> [fides] skipped (missing --fides-root)"
  else
    echo "==> [fides] starting"
    N_RUNS="$N_FIDES_RUNS" OUT_ROOT="$RUN_DIR/fides" \
      bash "$REPO_ROOT/scripts/run_fides_case_study.sh" \
      --fides-root "$FIDES_ROOT" \
      >"$RUN_DIR/fides.stdout.log" 2>"$RUN_DIR/fides.stderr.log"
    echo "==> [fides] done"
  fi
else
  echo "==> [fides] skipped"
fi

cat >"$RUN_DIR/run_meta.txt" <<EOF
timestamp=$STAMP
repo_root=$REPO_ROOT
run_internal=$RUN_INTERNAL
run_agentdojo=$RUN_AGENTDOJO
run_camel=$RUN_CAMEL
run_fides=$RUN_FIDES
agentdojo_root=$AGENTDOJO_ROOT
camel_root=$CAMEL_ROOT
fides_root=$FIDES_ROOT
k_verify=$K_VERIFY
k_corpus=$K_CORPUS
min_successes=$MIN_SUCCESSES
n_fides_runs=$N_FIDES_RUNS
EOF

echo "==> true full matrix complete: $RUN_DIR"
