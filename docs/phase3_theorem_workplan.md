# Phase 3 theorem workplan

This is the implementation checklist for the theorem-strengthening phase.

## 3.1 Formal class definition

Deliverable: `docs/theorem_labeled_data_architecture.md`

Must define:
- label domain and semantics,
- propagation function,
- gate-observable state,
- excluded architecture classes.

Instance mapping table required for:
- CaMeL
- FIDES
- SAFEFLOW
- `baseline_combined`

## 3.2 Full impossibility proof

Deliverable: updated `IMPOSSIBILITY_THEOREM.md` (or new `docs/impossibility_proof_full.md`)

Must include:
- explicit indistinguishability construction,
- theorem statement with assumptions,
- proof steps with references to definitions,
- conditions under which provenance-bound capabilities close the gap.

## 3.3 Internal adversarial review

Deliverable: `results/theorem_adversarial_review.md`

At least 3 counterexample attempts:
1) stronger label discipline
2) richer recipient constraints
3) adaptive planner + labels

For each:
- attempted construction,
- where theorem proof blocks it (or theorem revision if it succeeds).

## 3.4 External proof review

Deliverable: `results/theorem_external_review.md`

Capture:
- reviewer profile (anonymized),
- concerns raised,
- dispositions (fixed/rebutted/deferred),
- diff references to proof updates.

## Exit criteria

- proof is complete and non-circular,
- all known counterexample attempts documented,
- at least one external reviewer sign-off on defensibility.
