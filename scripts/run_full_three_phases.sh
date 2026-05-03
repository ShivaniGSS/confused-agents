#!/usr/bin/env bash
set -euo pipefail

# Full, no-budget execution for all three phases.
# Runs every fixture verifier + corpus evaluation across all available providers.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
[ -f .env ] && set -a && . .env && set +a

# Ensure API calls do not inherit a broken outbound proxy from shell/.env.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.anthropic.com,api.openai.com,api.together.xyz}"

K_VERIFY="${K_VERIFY:-4}"
K_CORPUS="${K_CORPUS:-10}"
MIN_SUCCESSES="${MIN_SUCCESSES:-2}"
OUT_ROOT="${OUT_ROOT:-results/full_three_phases}"

ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-6}"
TOGETHER_MODEL="${TOGETHER_MODEL:-meta-llama/Llama-3.3-70B-Instruct-Turbo}"
OPENAI_MODEL="${OPENAI_MODEL:-gpt-4.1}"

mkdir -p "$OUT_ROOT"

run_provider() {
  local provider="$1"
  local model="$2"

  echo "==> [$provider] Phase 1: fixture verification batch"
  python3 scripts/verify_fixture_batch.py \
    --fixtures-root attacks/fixtures \
    --provider "$provider" \
    --model "$model" \
    --k "$K_VERIFY" \
    --min-successes "$MIN_SUCCESSES" \
    --out "$OUT_ROOT/phase1_verification"

  echo "==> [$provider] Phase 2: full corpus (none, baseline_combined, capguard_full)"
  python -m harness.run_corpus \
    --scenarios scenario_a_calendar,scenario_b_docs,scenario_c_multitenant,scenario_d_purpose \
    --orchestrators minimal \
    --defenses none,baseline_combined,capguard_full \
    --provider "$provider" \
    --model "$model" \
    --k "$K_CORPUS" \
    --out "$OUT_ROOT/phase2_corpus/${provider}__${model//\//_}"
}

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  run_provider anthropic "$ANTHROPIC_MODEL"
else
  echo "==> skipping anthropic (ANTHROPIC_API_KEY not set)"
fi

if [ -n "${TOGETHER_API_KEY:-}" ]; then
  run_provider together "$TOGETHER_MODEL"
else
  echo "==> skipping together (TOGETHER_API_KEY not set)"
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  run_provider openai "$OPENAI_MODEL"
else
  echo "==> skipping openai (OPENAI_API_KEY not set)"
fi

echo "==> Phase 3: corpus audit + coverage check"
python3 scripts/corpus_audit.py \
  --verified-reports-root "$OUT_ROOT/phase1_verification" \
  --out "$OUT_ROOT/phase3_audit/corpus_audit.json"

echo "==> done. outputs: $OUT_ROOT"
