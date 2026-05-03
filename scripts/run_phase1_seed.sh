#!/usr/bin/env bash
set -euo pipefail

# Seed verifier runs for Phase 1 sanity checks.
# Usage:
#   scripts/run_phase1_seed.sh anthropic claude-sonnet-4-6
#   scripts/run_phase1_seed.sh together meta-llama/Llama-3.3-70B-Instruct-Turbo

PROVIDER="${1:-${PROVIDER:-anthropic}}"
MODEL="${2:-${MODEL:-claude-sonnet-4-6}}"
K="${K:-10}"
OUT="${OUT:-results/fixture_verification_seed}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

run_one() {
  local fixture="$1"
  echo "==> verify $fixture ($PROVIDER / $MODEL, k=$K)"
  python3 scripts/verify_fixture_mechanism.py \
    "$fixture" \
    --provider "$PROVIDER" \
    --model "$MODEL" \
    --k "$K" \
    --out "$OUT/${PROVIDER}/$(basename "$fixture")"
}

run_one attacks/fixtures/scenario_d_purpose/d_clin_1
run_one attacks/fixtures/scenario_d_purpose/d_clin_2
run_one attacks/fixtures/scenario_a_calendar/attack_02
run_one attacks/fixtures/scenario_a_calendar/attack_03
run_one attacks/fixtures/scenario_a_calendar/attack_04
run_one attacks/fixtures/scenario_a_calendar/attack_06

echo "==> done: $OUT"
