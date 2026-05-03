#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT_ROOT="${OUT_ROOT:-$ROOT/results/observability}"
DEFENSES="${DEFENSES:-none,model_safety,integrity_only,camel_style,capguard,trajectory_monitor,full_stack}"
SCENARIOS="${SCENARIOS:-$ROOT/scenarios/scenarios.json}"
PROVIDER="${PROVIDER:-anthropic}"
MODEL="${MODEL:-claude-sonnet-4-6}"
LIVE_LLM="${LIVE_LLM:-0}"
K="${K:-1}"

mkdir -p "$OUT_ROOT"

LIVE_ARG=""
if [[ "$LIVE_LLM" == "1" ]]; then
  LIVE_ARG="--live-llm"
fi

PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python -m harness.run_observability_matrix \
  --scenarios "$SCENARIOS" \
  --defenses "$DEFENSES" \
  --provider "$PROVIDER" \
  --model "$MODEL" \
  --k "$K" \
  $LIVE_ARG \
  --out "$OUT_ROOT/$(date +%Y%m%d-%H%M%S)"
