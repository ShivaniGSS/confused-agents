# THEOREMS.md — Formal statements and proof sketches

This document specifies the formal claims the paper makes. It serves
two purposes: (1) the paper's §4 (Authority Calculus) and §5
(Theorems) reference these statements directly; (2) `policy.py` and
its sub-modules (`policy_authority.py`, `policy_purpose.py`) implement
predicates that should map mechanically to clauses in these proofs.

The statements use the notation from `CLAUDE.md` §4 (as amended by
`CLAUDE_MD_CHANGES.md` Edit 4) and the lattice from
`PURPOSE_LATTICE.md`.

---

## Theorem 1 (Impossibility of trace-only purpose enforcement)

**Statement.** Let $A$ be an LLM agent operating under threat model
TM (CLAUDE.md §3, amended). Let $G$ be a runtime governor that
observes only the sequence of tool-call invocations $\langle T_{j_1}(a_1),
T_{j_2}(a_2), \ldots \rangle$ (the trace) and decides for each call
whether to permit or block. Then for any $G$, there exist purpose-
boundary attacks against $A$ that $G$ cannot block.

**Sketch.**

The proof is an indistinguishability argument. We construct two
agent runs $\mathcal{R}_1$ and $\mathcal{R}_2$ that produce
*identical* tool-call traces but where $\mathcal{R}_1$ is purpose-
consistent and $\mathcal{R}_2$ is a purpose-boundary violation.

Setup:
- $A$ has capability $\kappa$ with $\kappa.\mathsf{Purp} =
  \mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$.
- $A$'s context contains data record $d_{\text{alice}}$ with
  $L^{\text{purp}}(d_{\text{alice}}) =
  \mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$.
- $A$ executes $T_j(a)$ where $a$ contains a string (e.g., a name,
  a tool argument) that happens to match strings in $d_{\text{alice}}$.

In $\mathcal{R}_1$: $A$'s reasoning was driven by $d_{\text{alice}}$.
The capability is consistent, the call serves alice's care.

In $\mathcal{R}_2$: $A$'s context *also* contains $d_{\text{bob}}$
with $L^{\text{purp}}(d_{\text{bob}}) =
\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}bob}$, and
$A$'s reasoning was actually driven by $d_{\text{bob}}$. By
construction, $a$'s string content is consistent with both records
(e.g., a generic family-history note that mentions both subjects).
The trace $T_j(a)$ is identical to $\mathcal{R}_1$.

The governor $G$ sees only the trace. Both runs produce trace
$\langle T_j(a) \rangle$. $G$ cannot distinguish $\mathcal{R}_1$
from $\mathcal{R}_2$. If $G$ permits, $\mathcal{R}_2$ slips through
(purpose violation). If $G$ blocks, $\mathcal{R}_1$ is incorrectly
blocked (false positive on legitimate care). Therefore no $G$
observing only traces can correctly classify both runs.

**Why this matters.** The theorem says: enforcement requires
*observing what data drove the call*, not just observing the call.
That observation is the provenance side channel. Without it, runtime
enforcement of purpose binding is impossible.

**Caveat.** The theorem assumes $G$ has no other oracle (e.g., model
internals, human approval). With a human-approval oracle on every
tool call, enforcement is trivial but at extreme cost; the theorem
addresses *automated* runtime enforcement, which is the deployment
regime that matters.

**Where this is used in the paper.** §5 introduces this theorem
immediately before §6 introduces CapGuard's provenance side channel.
The theorem motivates the side channel as not just useful but
necessary.

---

## Theorem 2 (Sufficiency of provenance for purpose enforcement)

**Statement.** Let $G^+$ be a runtime governor that observes (a) the
tool-call trace, *and* (b) for each datum $d$ in the agent's context,
the ground-truth labels $(L^{\text{auth}}(d), L^{\text{purp}}(d))$
provided through a side channel. Then $G^+$ can enforce both
authority consistency and purpose consistency under the calculus of
§4.

**Sketch.**

Constructive. We exhibit such a $G^+$: it is CapGuard with full
provenance. For each tool call $T_j(a)$:

1. Compute $L^{\text{auth}}(a) = \bigcup_d L^{\text{auth}}(d)$ over
   data $d$ that propagated into $a$. Check $\kappa_j.P \in
   L^{\text{auth}}(a)$.
2. Compute $\bigsqcup_d L^{\text{purp}}(d)$ over data $d$ that
   propagated into $a$. Check $\kappa_j.\mathsf{Purp} \le \bigsqcup$.
3. If $\kappa_j.\mathsf{Purp}$ is subject-bound, compute
   $\mathsf{subject}(a)$ from the extraction table
   (`PURPOSE_LATTICE.md` §5). Check
   $\mathsf{subject}(a) = \kappa_j.\mathsf{Purp}.\mathsf{subject}$.
4. If all three checks pass, permit. Else block.

The claim is that $G^+$ correctly enforces consistency *given that
provenance labels are accurate.* This is a soundness-with-respect-to-
labels claim, not soundness-with-respect-to-truth. The paper is
explicit about this.

**Caveat about propagation precision.** The proof assumes labels
propagate accurately through the agent's reasoning. In practice
(`provenance.py`), substring matching is the propagation mechanism;
it is sound (over-approximates) but not precise (may attribute labels
to spans that didn't actually flow from the source). The
soundness/precision tradeoff is documented empirically in
`EMPIRICAL_DESIGN.md` §6.1; the theorem is a statement about the
limit case where propagation is perfect.

---

## Theorem 3 (Provenance is the minimal sufficient side channel)

**Statement.** Any side channel sufficient to enforce purpose
consistency on the threat model TM must include, for each datum in
the agent's context, information at least as fine-grained as the
purpose label $L^{\text{purp}}(d)$.

**Sketch.**

By contradiction. Suppose a side channel $S$ is sufficient but does
not include purpose-equivalent information. Then $S$ cannot
distinguish two contexts that differ only in their purpose labels.
But two such contexts can produce traces that should be classified
differently (per Theorem 1's construction). Contradiction.

**What this rules out.** Side channels that report only "trusted vs
untrusted" (FIDES integrity), only "data lineage by source" (CaMeL
provenance tags without purpose annotation), or only "principal of
origin" (authority-flow alone). All of these are strict abstractions
of full purpose labels.

**What this allows.** Any side channel that conveys at least the
purpose lattice's $L^{\text{purp}}$ information. Richer channels
(e.g., adding intent classification) are also allowed but are not
necessary.

**Where this is used in the paper.** §5, immediately after Theorem 2.
Together, T1 (necessity), T2 (sufficiency), T3 (minimality)
characterize the side channel exactly.

---

## Theorem 4 (Pre-invocation enforcement is necessary for irreversible tools)

**Statement.** For a tool $T$ whose action is irreversible — i.e.,
once the call is committed, no subsequent action by any party can
undo the effect — and whose commit latency $\ell_T$ is shorter than
any feasible detection latency $\ell_D$, post-hoc detection cannot
prevent the harm of a purpose-boundary violation. Pre-invocation
checking is necessary.

**Sketch.**

The harm of a purpose-boundary violation occurs at commit time. By
hypothesis, $\ell_T < \ell_D$, so any detector observing the trace
flags the violation only after the commit. The detector's flag has
audit value but no preventive value — the irreversible action has
already occurred.

A pre-invocation check, by contrast, runs *before* the commit. If the
check completes before the commit (which is implementation-controlled,
not constrained by the same latency relationship), the action can be
blocked.

**Why this matters.** The theorem says: detection-only defenses are
strictly insufficient for the irreversible-tool class, no matter how
fast the detector. CapGuard's `irreversibility.py` implements the
pre-invocation check; the theorem motivates why this is the only
defense category that can prevent harm on this class of tools.

**Where this is used in the paper.** §5 (Theorems) and §6.3
(commit-race case study).

**Empirical companion.** `EMPIRICAL_DESIGN.md` §6.2 demonstrates this
empirically: detection-only catches the violation in the trace but
the commit has already occurred; CapGuard pre-invocation prevents.

---

## Implementation correspondence

Each theorem maps to specific code clauses. Reviewers can audit the
mapping.

| Theorem | Code |
|---|---|
| T1 (impossibility) | Negative result; not implemented. Referenced in `policy.py` docstring as motivation. |
| T2 (sufficiency) | `policy.py` composition of `policy_authority.py` and `policy_purpose.py`, both consuming labels from `provenance.py`. |
| T2 step 1 | `policy_authority.py:check_authority` |
| T2 step 2 | `policy_purpose.py:check_purpose_join` |
| T2 step 3 | `policy_purpose.py:check_subject_match` |
| T3 (minimality) | The mock servers' provenance side channel (in `mock_mcp/_common.py`) carries purpose labels. The integrity-only baseline (`baselines/integrity_only.py`) carries strictly less, demonstrating insufficiency. |
| T4 (irreversibility) | `irreversibility.py` performs the pre-invocation check; tools tagged `irreversible` route through it. |

If the code drifts from the theorems, the paper's claims become
inconsistent with the artifact. CI check: `python harness/
check_theorem_correspondence.py` walks the predicate definitions in
the policy modules and verifies they match the theorem statements
above. Failure surfaces immediately.

---

## What is *not* claimed

To be honest about scope:

- **The paper does not claim CapGuard is sound under arbitrary
  propagation.** Substring matching is not perfect. The paper claims
  CapGuard is sound *given accurate labels* and characterizes
  propagation accuracy empirically.
- **The paper does not claim purpose binding is the only thing that
  matters.** Authority consistency catches a different attack class
  (families A, B, C). The contribution is that purpose binding catches
  a *previously-unaddressed* class (family D) and is theoretically
  necessary (T1) for that class.
- **The paper does not claim Theorem 1 holds for all conceivable
  enforcement architectures.** It holds for the trace-only governor
  class. Other architectures (model-internal interpretation, formal
  verification at training time, etc.) are not ruled out — they are
  outside the threat model.
- **The paper does not claim the lattice from `PURPOSE_LATTICE.md`
  is the only correct lattice.** It claims it is sufficient for the
  evaluation and is one realization of the framework. Different
  deployments would specialize the lattice to their domain.

These caveats appear in the paper's "Limitations" subsection.

---

End of THEOREMS.md.
