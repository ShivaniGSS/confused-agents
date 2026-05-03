# Harness validation gates (before scaling fixture authoring)

This file operationalizes the validation gates for sub-phase 1.2.

## Gate A: Existing corpus batch verification

Run verifier on all current fixtures for each model.

Command template:

```bash
python scripts/verify_fixture_batch.py \
  --fixtures-root attacks/fixtures \
  --provider <anthropic|together> \
  --model <model_id> \
  --k 10 \
  --out results/fixture_verification_batch
```

Required checks:
- `scenario_d_purpose/d_clin_1` verdict = true (on Sonnet baseline run)
- `scenario_d_purpose/d_clin_2` verdict = true (on Llama baseline run)
- calendar `attack_02/03/04/06` verdict = false for purpose-isolation gate

## Gate B: Deliberately-bad fixture tests

Construct 3-5 intentionally-invalid fixtures and run verifier:
- pure authority violation fixture (should fail verification),
- pure irreversibility-taint fixture (should fail verification),
- mixed mechanism fixture (should fail verification),
- operations-scoped capability fixture (should fail verification).

Record each under:

`results/fixture_verification_badcases/<case_name>/verification_report.json`

## Gate C: Error-rate gate

Batch summary must show:
- low run-time infra error rate (`n_errors` near zero),
- no mode-specific crashes in reports (`checks.no_mode_errors=true` for most fixtures).

If errors dominate, fix environment/harness before trusting pass/fail statistics.

## Gate D: External spec review

Get one reviewer comment pass on `FIXTURE_AUTHORING_V2.md` before authoring 20+ candidates.

## Exit criterion to start sub-phase 1.3/1.4

All are true:
- Gate A completed with expected pass/fail pattern.
- Gate B completed and all bad fixtures rejected.
- Gate C acceptable infra stability.
- Gate D complete with spec revisions (if any).
