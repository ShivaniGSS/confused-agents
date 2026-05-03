#!/bin/bash
# One-command full reproduction (CLAUDE.md Section 11).
#
# Reproduces every paper experiment from a fresh clone. Total runtime
# budget: under 4 hours on a single machine with API access. LLM
# responses are cached in results/llm_cache/ keyed by hash of
# (prompt, model, settings) so repeat runs do not re-bill.
#
# Pre-requisites:
#   * .env populated from .env.example with at least one provider key
#   * python -m venv .venv && source .venv/bin/activate
#   * pip install -r requirements.txt
#   * The four CapGuard policy modules
#       (capguard/{capability,provenance,policy,irreversibility}.py)
#     must be human-implemented per CLAUDE.md hard rule 8 — this script
#     will fail loudly with NotImplementedError if any are still stubs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
[ -f .env ] && set -a && . .env && set +a

# Ensure API calls do not inherit a broken outbound proxy from shell/.env.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.anthropic.com,api.openai.com,api.together.xyz}"

K="${K:-10}"
PROVIDER="${PROVIDER:-anthropic}"
FRONTIER_MODEL="${FRONTIER_MODEL:-claude-sonnet-4-6}"
# Serverless id (non-Turbo 70B requires a dedicated endpoint on Together).
OPEN_MODEL="${OPEN_MODEL:-meta-llama/Llama-3.3-70B-Instruct-Turbo}"
OPENAI_MODEL="${OPENAI_MODEL:-gpt-4.1}"
RESULTS_DIR="${RESULTS_DIR:-./results}"

mkdir -p "$RESULTS_DIR" "$RESULTS_DIR/llm_cache"

echo "==> step 1: no defense on active fixture set (frontier model)"
python -m harness.run_corpus \
    --scenarios scenario_a_calendar,scenario_b_docs,scenario_d_purpose \
    --orchestrators minimal \
    --defenses none \
    --provider "$PROVIDER" --model "$FRONTIER_MODEL" \
    --k "$K" \
    --out "$RESULTS_DIR/none_frontier"

echo "==> step 2: baseline_combined on active fixture set (frontier model)"
python -m harness.run_corpus \
    --scenarios scenario_a_calendar,scenario_b_docs,scenario_d_purpose \
    --orchestrators minimal \
    --defenses baseline_combined \
    --provider "$PROVIDER" --model "$FRONTIER_MODEL" \
    --k "$K" \
    --out "$RESULTS_DIR/baseline_combined_frontier"

echo "==> step 3: capguard_full on active fixture set (frontier model)"
python -m harness.run_corpus \
    --scenarios scenario_a_calendar,scenario_b_docs,scenario_d_purpose \
    --orchestrators minimal \
    --defenses capguard_full \
    --provider "$PROVIDER" --model "$FRONTIER_MODEL" \
    --k "$K" \
    --out "$RESULTS_DIR/capguard_full_frontier"

echo "==> step 4: benign workload under capguard_full (frontier model)"
python -m harness.run_benign \
    --orchestrators minimal \
    --capguard on \
    --provider "$PROVIDER" --model "$FRONTIER_MODEL" \
    --k "$K" \
    --out "$RESULTS_DIR/benign_frontier"

echo "==> step 5: cross-model runs (none, baseline_combined, capguard_full)"
if [ -n "${TOGETHER_API_KEY:-}" ]; then
  python -m harness.run_corpus \
      --scenarios scenario_a_calendar,scenario_b_docs,scenario_d_purpose \
      --orchestrators minimal --defenses none,baseline_combined,capguard_full \
      --provider together --model "$OPEN_MODEL" \
      --k "$K" \
      --out "$RESULTS_DIR/ablation_openmodel"
else
  echo "    (skipping: TOGETHER_API_KEY not set; this is the optional open-model ablation)"
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
  python -m harness.run_corpus \
      --scenarios scenario_a_calendar,scenario_b_docs,scenario_d_purpose \
      --orchestrators minimal --defenses none,baseline_combined,capguard_full \
      --provider openai --model "$OPENAI_MODEL" \
      --k "$K" \
      --out "$RESULTS_DIR/ablation_openai"
else
  echo "    (skipping: OPENAI_API_KEY not set; this is the optional GPT ablation)"
fi

echo "==> step 6: commit-race case study"
python -m harness.run_attack \
    attacks/fixtures/commit_race/attack_01 \
    --orchestrator minimal --defense none \
    --provider "$PROVIDER" --model "$FRONTIER_MODEL" \
    --k "$K" \
    --out "$RESULTS_DIR/commit_race/baseline"
python -m harness.run_attack \
    attacks/fixtures/commit_race/attack_01 \
    --orchestrator minimal --defense capguard_full \
    --provider "$PROVIDER" --model "$FRONTIER_MODEL" \
    --k "$K" \
    --out "$RESULTS_DIR/commit_race/capguard"

echo "==> step 7: generate paper tables"
mkdir -p paper_outputs
jupyter nbconvert --to notebook --execute notebooks/generate_tables.ipynb \
    --output ../paper_outputs/generate_tables.executed.ipynb

echo "==> done. Outputs in $RESULTS_DIR and ./paper_outputs/."
