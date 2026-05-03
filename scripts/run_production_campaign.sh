#!/usr/bin/env bash
set -euo pipefail

# Production-hardened campaign runner:
# - resumable checkpoints
# - retries for long-running stages
# - staged axis/model execution to control runtime risk
# - unified manifest + merged report output

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.openai.com,api.anthropic.com,api.together.xyz}"

OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/results/production_campaign}"
STAMP="${STAMP:-$(date +%Y%m%d-%H%M%S)}"
CAMPAIGN_DIR="${CAMPAIGN_DIR:-$OUT_ROOT/$STAMP}"
STATE_DIR="$CAMPAIGN_DIR/state"
MANIFEST="$CAMPAIGN_DIR/campaign_manifest.jsonl"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_SLEEP_S="${RETRY_SLEEP_S:-8}"

RUN_OBSERVABILITY="${RUN_OBSERVABILITY:-1}"
RUN_INTERNAL="${RUN_INTERNAL:-0}"
RUN_AGENTDOJO="${RUN_AGENTDOJO:-0}"
RUN_CAMEL="${RUN_CAMEL:-0}"
RUN_FIDES="${RUN_FIDES:-0}"

LIVE_LLM="${LIVE_LLM:-1}"
# Paper / RESEARCH_PLAN.md §4.1: k=10 repeats per scenario×defense for Wilson intervals.
OBS_K="${OBS_K:-10}"
DEFENSES="${DEFENSES:-none,model_safety,integrity_only,camel_style,capguard,trajectory_monitor,full_stack}"
MODELS="${MODELS:-openai:gpt-4.1,anthropic:claude-sonnet-4-6,together:meta-llama/Llama-3.3-70B-Instruct-Turbo}"
AXES="${AXES:-A,B,C,D,E,F,G,H}"
SCENARIOS_JSON="${SCENARIOS_JSON:-$REPO_ROOT/scenarios/scenarios.json}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LLM_CACHE_DIR="${LLM_CACHE_DIR:-$REPO_ROOT/results/llm_cache}"

AGENTDOJO_ROOT="${AGENTDOJO_ROOT:-}"
CAMEL_ROOT="${CAMEL_ROOT:-}"
FIDES_ROOT="${FIDES_ROOT:-}"

mkdir -p "$CAMPAIGN_DIR" "$STATE_DIR"

log_manifest() {
  local stage="$1"
  local key="$2"
  local ok="$3"
  local artifact="${4:-}"
  local provider="${5:-}"
  local model="${6:-}"
  local defense_matrix="${7:-}"
  local degradation="${8:-}"
  python - <<'PY' "$MANIFEST" "$stage" "$key" "$ok" "$artifact" "$provider" "$model" "$defense_matrix" "$degradation"
import json,sys,time
path,stage,key,ok,artifact,provider,model,dm,dg=sys.argv[1:]
row={
  "ts": int(time.time()),
  "stage": stage,
  "key": key,
  "ok": ok == "1",
  "artifact": artifact or None,
  "provider": provider or None,
  "model": model or None,
  "defense_matrix": dm or None,
  "degradation_curves": dg or None,
}
with open(path, "a") as f:
  f.write(json.dumps(row, sort_keys=True) + "\n")
PY
}

run_with_retry() {
  local key="$1"
  shift
  local n=1
  while true; do
    if "$@"; then
      return 0
    fi
    if (( n >= MAX_RETRIES )); then
      return 1
    fi
    echo "==> retry $n/$MAX_RETRIES for $key after ${RETRY_SLEEP_S}s"
    sleep "$RETRY_SLEEP_S"
    n=$((n + 1))
  done
}

write_axis_subset() {
  local axis="$1"
  local out="$2"
  "$PYTHON_BIN" - <<'PY' "$SCENARIOS_JSON" "$axis" "$out"
import json,sys
src,axis,out=sys.argv[1:]
obj=json.load(open(src))
obj["scenarios"]=[s for s in obj.get("scenarios",[]) if str(s.get("axis",""))==axis]
json.dump(obj, open(out,"w"))
print(out)
PY
}

if [[ "$RUN_OBSERVABILITY" == "1" ]]; then
  IFS=',' read -r -a MODEL_ARR <<< "$MODELS"
  IFS=',' read -r -a AXIS_ARR <<< "$AXES"
  for m in "${MODEL_ARR[@]}"; do
    provider="${m%%:*}"
    model="${m#*:}"
    for axis in "${AXIS_ARR[@]}"; do
      key="obs__${provider}__${model//\//_}__axis_${axis}"
      done_file="$STATE_DIR/$key.done"
      if [[ -f "$done_file" ]]; then
        echo "==> [skip] $key already completed"
        continue
      fi
      subset="$CAMPAIGN_DIR/scenarios_axis_${axis}.json"
      write_axis_subset "$axis" "$subset" >/dev/null
      out_dir="$CAMPAIGN_DIR/observability/${provider}__${model//\//_}__axis_${axis}"
      mkdir -p "$out_dir"

      cmd=("$PYTHON_BIN" -m harness.run_observability_matrix
        --scenarios "$subset"
        --defenses "$DEFENSES"
        --provider "$provider"
        --model "$model"
        --k "$OBS_K"
        --cache-dir "$LLM_CACHE_DIR"
        --out "$out_dir")
      if [[ "$LIVE_LLM" == "1" ]]; then
        cmd+=(--live-llm)
      fi

      if run_with_retry "$key" env PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "${cmd[@]}" >"$out_dir/stdout.log" 2>"$out_dir/stderr.log"; then
        touch "$done_file"
        log_manifest "observability" "$key" "1" "$out_dir" "$provider" "$model" "$out_dir/defense_landscape_matrix.json" "$out_dir/degradation_curves.json"
      else
        log_manifest "observability" "$key" "0" "$out_dir" "$provider" "$model"
      fi
    done
  done
fi

if [[ "$RUN_INTERNAL" == "1" ]]; then
  key="internal_three_phases"
  done_file="$STATE_DIR/$key.done"
  if [[ ! -f "$done_file" ]]; then
    out_dir="$CAMPAIGN_DIR/internal"
    mkdir -p "$out_dir"
    if run_with_retry "$key" bash "$REPO_ROOT/scripts/run_full_three_phases.sh" >"$out_dir/stdout.log" 2>"$out_dir/stderr.log"; then
      touch "$done_file"
      log_manifest "internal" "$key" "1" "$out_dir"
    else
      log_manifest "internal" "$key" "0" "$out_dir"
    fi
  fi
fi

if [[ "$RUN_AGENTDOJO" == "1" && -n "$AGENTDOJO_ROOT" ]]; then
  key="agentdojo"
  done_file="$STATE_DIR/$key.done"
  if [[ ! -f "$done_file" ]]; then
    out_dir="$CAMPAIGN_DIR/agentdojo"
    mkdir -p "$out_dir"
    if run_with_retry "$key" bash "$REPO_ROOT/scripts/run_agentdojo_benchmarks.sh" --agentdojo-root "$AGENTDOJO_ROOT" --out-root "$out_dir" >"$out_dir/stdout.log" 2>"$out_dir/stderr.log"; then
      touch "$done_file"
      log_manifest "agentdojo" "$key" "1" "$out_dir"
    else
      log_manifest "agentdojo" "$key" "0" "$out_dir"
    fi
  fi
fi

if [[ "$RUN_CAMEL" == "1" && -n "$CAMEL_ROOT" ]]; then
  key="camel"
  done_file="$STATE_DIR/$key.done"
  if [[ ! -f "$done_file" ]]; then
    out_dir="$CAMPAIGN_DIR/camel"
    mkdir -p "$out_dir"
    if run_with_retry "$key" bash "$REPO_ROOT/scripts/run_camel_benchmarks.sh" --camel-root "$CAMEL_ROOT" --out-root "$out_dir" >"$out_dir/stdout.log" 2>"$out_dir/stderr.log"; then
      touch "$done_file"
      log_manifest "camel" "$key" "1" "$out_dir"
    else
      log_manifest "camel" "$key" "0" "$out_dir"
    fi
  fi
fi

if [[ "$RUN_FIDES" == "1" && -n "$FIDES_ROOT" ]]; then
  key="fides"
  done_file="$STATE_DIR/$key.done"
  if [[ ! -f "$done_file" ]]; then
    out_dir="$CAMPAIGN_DIR/fides"
    mkdir -p "$out_dir"
    if run_with_retry "$key" bash "$REPO_ROOT/scripts/run_fides_case_study.sh" --fides-root "$FIDES_ROOT" --out-root "$out_dir" >"$out_dir/stdout.log" 2>"$out_dir/stderr.log"; then
      touch "$done_file"
      log_manifest "fides" "$key" "1" "$out_dir"
    else
      log_manifest "fides" "$key" "0" "$out_dir"
    fi
  fi
fi

env PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" "$REPO_ROOT/scripts/merge_production_report.py" --campaign-dir "$CAMPAIGN_DIR" --out "$CAMPAIGN_DIR/unified_report.json" >/dev/null

cat >"$CAMPAIGN_DIR/run_meta.txt" <<EOF
campaign_dir=$CAMPAIGN_DIR
run_observability=$RUN_OBSERVABILITY
run_internal=$RUN_INTERNAL
run_agentdojo=$RUN_AGENTDOJO
run_camel=$RUN_CAMEL
run_fides=$RUN_FIDES
live_llm=$LIVE_LLM
obs_k=$OBS_K
defenses=$DEFENSES
models=$MODELS
axes=$AXES
scenarios_json=$SCENARIOS_JSON
max_retries=$MAX_RETRIES
retry_sleep_s=$RETRY_SLEEP_S
agentdojo_root=$AGENTDOJO_ROOT
camel_root=$CAMEL_ROOT
fides_root=$FIDES_ROOT
EOF

echo "==> production campaign complete: $CAMPAIGN_DIR"
echo "==> unified report: $CAMPAIGN_DIR/unified_report.json"
