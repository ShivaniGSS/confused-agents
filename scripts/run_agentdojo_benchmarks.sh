#!/usr/bin/env bash
set -euo pipefail

# Run AgentDojo benchmark matrix with unified output layout.
#
# Required:
#   --agentdojo-root /path/to/agentdojo
#
# Optional env:
#   OUT_ROOT=results/external_agentdojo
#   MODEL_ENUMS="GPT_4O_2024_05_13,CLAUDE_3_7_SONNET_20250219"
#   DEFENSES="tool_filter"
#   ATTACKS="tool_knowledge"
#   SUITES="workspace"
#   USER_TASKS="user_task_0,user_task_1"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.openai.com,api.anthropic.com,api.together.xyz}"

AGENTDOJO_ROOT=""
OUT_ROOT="${OUT_ROOT:-$REPO_ROOT/results/external_agentdojo}"
MODEL_ENUMS="${MODEL_ENUMS:-GPT_4O_2024_05_13,CLAUDE_3_7_SONNET_20250219}"
DEFENSES="${DEFENSES:-tool_filter}"
ATTACKS="${ATTACKS:-tool_knowledge}"
SUITES="${SUITES:-workspace}"
USER_TASKS="${USER_TASKS:-user_task_0,user_task_1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agentdojo-root)
      AGENTDOJO_ROOT="$2"
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

if [[ -z "$AGENTDOJO_ROOT" ]]; then
  echo "Missing required --agentdojo-root /path/to/agentdojo" >&2
  exit 2
fi

if [[ ! -f "$AGENTDOJO_ROOT/src/agentdojo/scripts/benchmark.py" ]]; then
  echo "Invalid AgentDojo root: benchmark.py not found under $AGENTDOJO_ROOT/src/agentdojo/scripts" >&2
  exit 2
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUT_ROOT/$STAMP"
mkdir -p "$RUN_DIR"

IFS=',' read -r -a MODEL_ARR <<< "$MODEL_ENUMS"
IFS=',' read -r -a DEF_ARR <<< "$DEFENSES"
IFS=',' read -r -a ATK_ARR <<< "$ATTACKS"
IFS=',' read -r -a SUITE_ARR <<< "$SUITES"
IFS=',' read -r -a TASK_ARR <<< "$USER_TASKS"

echo "==> AgentDojo root: $AGENTDOJO_ROOT"
echo "==> output dir: $RUN_DIR"

for model in "${MODEL_ARR[@]}"; do
  for defense in "${DEF_ARR[@]}"; do
    for attack in "${ATK_ARR[@]}"; do
      for suite in "${SUITE_ARR[@]}"; do
        CELL_DIR="$RUN_DIR/${model}__${defense}__${attack}__${suite}"
        mkdir -p "$CELL_DIR"
        echo "==> running model=$model defense=$defense attack=$attack suite=$suite"
        (
          cd "$AGENTDOJO_ROOT"
          cmd=(python -m agentdojo.scripts.benchmark -s "$suite" --model "$model" --defense "$defense" --attack "$attack" --logdir "$CELL_DIR")
          for ut in "${TASK_ARR[@]}"; do
            cmd+=(-ut "$ut")
          done
          "${cmd[@]}" >"$CELL_DIR/stdout.log" 2>"$CELL_DIR/stderr.log"
        )
        echo "==> done: $CELL_DIR"
      done
    done
  done
done

cat >"$RUN_DIR/run_meta.txt" <<EOF
agentdojo_root=$AGENTDOJO_ROOT
model_enums=$MODEL_ENUMS
defenses=$DEFENSES
attacks=$ATTACKS
suites=$SUITES
user_tasks=$USER_TASKS
timestamp=$STAMP
EOF

echo "==> AgentDojo matrix complete: $RUN_DIR"
