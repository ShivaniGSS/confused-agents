# Staged Production Campaign Runbook

This runbook defines the recommended execution strategy for paper-grade evaluation with:

- observability axes `A..H`
- defense classes
- multiple models (GPT, Claude, Llama)
- external validation tracks (AgentDojo, CAMEL, FIDES)
- repeated trials per cell (`k`) for confidence intervals

It uses the hardened orchestrator:

- `scripts/run_production_campaign.sh`

which provides:

- retries for flaky stages
- resumable checkpoints
- stage-by-stage manifest logging
- unified merged reporting

---

## Why staged instead of one giant run

Even with hardening, staged execution is still preferred for first full runs:

- isolates provider/network failures quickly
- avoids rerunning everything when one stage fails
- keeps model-by-model provenance cleaner for paper tables
- reduces overnight runtime risk

After one clean staged pass, you can run broader one-shot campaigns confidently.

---

## Matrix target and how this approach builds it

## Intended matrix shape

- **Rows:** Axes `A..H`
  - A: Multi-turn purpose drift
  - B: Compositional injection
  - C: Cross-tool provenance laundering
  - D: Pretextual legitimacy
  - E: Adaptive multi-step attack
  - F: Temporal decoupling
  - G: Privilege escalation through tool-chain composition
  - H: Tool metadata/environment poisoning

- **Columns (defense classes):**
  - `none`
  - `model_safety`
  - `integrity_only`
  - `camel_style`
  - `capguard`
  - `trajectory_monitor`
  - `full_stack`

- **Model dimension (separate matrix per model):**
  - GPT
  - Claude
  - Llama

## How runs map to matrix cells

For each model pass, the campaign runs:

- all selected axes (`A..H`)
- all selected defenses (7 classes)
- both run types:
  - `attack`
  - `benign` (for FPR)

This yields per-cell metrics in `defense_landscape_matrix.json`:

- `attack_success_rate`
- `detection_rate`
- `false_positive_rate`
- `mean_detection_horizon`
- Wilson CI bounds for:
  - attack success
  - detection
  - false positive rate
- model-safety attribution rates:
  - `model_safety_executed_rate`
  - `model_safety_refused_rate`
  - `model_safety_partial_rate`
  - `model_safety_failed_rate`

`degradation_curves.json` adds per-axis-parameter slices.

---

## One-time shell prep

```bash
cd "$(pwd)"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,api.openai.com,api.anthropic.com,api.together.xyz}"
```

Ensure provider keys are present in the environment before live runs:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `TOGETHER_API_KEY`

---

## Staged execution sequence (recommended)

### 1) GPT observability matrix (A-H, 7 defenses)

```bash
LIVE_LLM=1 \
RUN_OBSERVABILITY=1 RUN_INTERNAL=0 RUN_AGENTDOJO=0 RUN_CAMEL=0 RUN_FIDES=0 \
MODELS="openai:gpt-4.1" \
DEFENSES="none,model_safety,integrity_only,camel_style,capguard,trajectory_monitor,full_stack" \
AXES="A,B,C,D,E,F,G,H" \
OBS_K=10 \
OUT_ROOT="$PWD/results/production_campaign" STAMP="gpt_obs_$(date +%Y%m%d-%H%M%S)" \
bash scripts/run_production_campaign.sh
```

### 2) Claude observability matrix

```bash
LIVE_LLM=1 \
RUN_OBSERVABILITY=1 RUN_INTERNAL=0 RUN_AGENTDOJO=0 RUN_CAMEL=0 RUN_FIDES=0 \
MODELS="anthropic:claude-sonnet-4-6" \
DEFENSES="none,model_safety,integrity_only,camel_style,capguard,trajectory_monitor,full_stack" \
AXES="A,B,C,D,E,F,G,H" \
OBS_K=10 \
OUT_ROOT="$PWD/results/production_campaign" STAMP="claude_obs_$(date +%Y%m%d-%H%M%S)" \
bash scripts/run_production_campaign.sh
```

### 3) Llama observability matrix

```bash
LIVE_LLM=1 \
RUN_OBSERVABILITY=1 RUN_INTERNAL=0 RUN_AGENTDOJO=0 RUN_CAMEL=0 RUN_FIDES=0 \
MODELS="together:meta-llama/Llama-3.3-70B-Instruct-Turbo" \
DEFENSES="none,model_safety,integrity_only,camel_style,capguard,trajectory_monitor,full_stack" \
AXES="A,B,C,D,E,F,G,H" \
OBS_K=10 \
OUT_ROOT="$PWD/results/production_campaign" STAMP="llama_obs_$(date +%Y%m%d-%H%M%S)" \
bash scripts/run_production_campaign.sh
```

### 4) External validation tracks

```bash
LIVE_LLM=0 \
RUN_OBSERVABILITY=0 RUN_INTERNAL=1 RUN_AGENTDOJO=1 RUN_CAMEL=1 RUN_FIDES=1 \
AGENTDOJO_ROOT="/ABS/PATH/TO/agentdojo" \
CAMEL_ROOT="/ABS/PATH/TO/camel" \
FIDES_ROOT="/ABS/PATH/TO/fides" \
OUT_ROOT="$PWD/results/production_campaign" STAMP="external_tracks_$(date +%Y%m%d-%H%M%S)" \
bash scripts/run_production_campaign.sh
```

---

## Produced artifacts

Each campaign directory includes:

- `campaign_manifest.jsonl`  
  Stage-level outcomes, artifacts, and status.

- `unified_report.json`  
  Merged summary over observability + external tracks.

- observability stage outputs per model/axis:
  - `defense_landscape_matrix.json`
  - `degradation_curves.json`
  - `summary.jsonl`
  - per-turn traces

---

## Paper assembly guidance

To build the intended headline matrix:

1. Use each model campaign's `defense_landscape_matrix.json`.
2. Keep rows as axes `A..H`.
3. Keep columns as 7 defense classes.
4. Present one matrix per model, plus optional cross-model deltas.
5. Use `degradation_curves.json` for axis-parameter figures.
6. Use `model_safety_*_rate` fields to support claims about inherent model refusal vs execution behavior.

External tracks (AgentDojo/CAMEL/FIDES) are reported as complementary validation, not replacements for the core A-H x defense matrix.
