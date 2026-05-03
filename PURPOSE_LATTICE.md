# PURPOSE_LATTICE.md — Canonical purpose lattice for CapGuard

This document specifies the purpose lattice $(\Pi, \le, \sqcup)$ used
throughout the paper, the artifact, and the evaluation. Every
capability minted in CapGuard, every datum in every fixture, and every
purpose-consistency check refers to this lattice. The lattice is
canonical: do not introduce purposes outside it without formally
extending the lattice and updating this document, `THEOREMS.md`, and
`capguard/purpose_lattice.py` together.

---

## 1. What the lattice is for

A capability $\kappa$ carries a purpose $\kappa.\mathsf{Purp} \in \Pi$
indicating the purpose for which it was issued. A datum $d$ in the
agent's reasoning context carries a purpose $L^{\text{purp}}(d) \in
\Pi$ indicating the purpose under which it was authored.

A tool call $T_j(a)$ presenting capability $\kappa_j$ is *purpose-
consistent* iff
$$\kappa_j.\mathsf{Purp} \le \bigsqcup_{d \in \mathsf{justify}(a)} L^{\text{purp}}(d)$$
i.e., the capability's purpose is at-or-below the join of the purposes
of the data motivating the call.

This is purpose attenuation in capability-system tradition: a
capability cannot be exercised in service of a broader purpose than
the purposes its justifying data was authored under.

---

## 2. Lattice structure

$\Pi$ is a partial order with finite joins. We construct it as a tree
plus a top element.

**Top element.** $\top \in \Pi$ — maximally permissive purpose. Used
for capabilities that are intentionally unrestricted in purpose
(e.g., a system-administrator's session-mint capability). For all
$p \in \Pi$, $p \le \top$.

**Bottom element.** We do not commit to a $\bot$. Some lattice
formulations require it; ours does not, and the consistency
predicate does not need it. If a purpose-flow analysis encounters a
datum with no inferable purpose, the conservative over-approximation
is to label it $\top$ (which makes it broadly usable but means
capabilities at $\top$ are required to use it under purpose
consistency). See §6 for the rationale.

**Roots.** The lattice has three roots immediately below $\top$, one per
domain represented in the evaluation:

- $\mathsf{clinical{\text{-}}care}$: actions in service of providing
  medical care to patients.
- $\mathsf{financial{\text{-}}advisory}$: actions in service of providing
  financial advice or executing financial decisions for clients.
- $\mathsf{operations}$: ordinary business operations (calendar
  management, document collaboration, internal communications). This
  is the root for fixtures in families A, B, and C of the corpus.

These three are pairwise incomparable:
$\mathsf{clinical{\text{-}}care} \not\le \mathsf{financial{\text{-}}advisory}$,
etc. The join of any two of them is $\top$.

**Refinements (subjects).** Below each root, refinements bind the
purpose to a specific subject. The convention is
$\mathsf{root}/\mathsf{subject{\text{=}}}X$ where $X$ is a principal
identifier. Examples:

- $\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$
- $\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}bob}$
- $\mathsf{financial{\text{-}}advisory}/\mathsf{client{\text{=}}carol}$
- $\mathsf{operations}/\mathsf{project{\text{=}}phoenix}$

Subject-bound refinements are below their roots:
$\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice} \le
\mathsf{clinical{\text{-}}care}$. Two subject-bound refinements with
different subjects are incomparable; their join is the parent root.

**Refinements (sub-purposes, optional).** For richer evaluation, a
root may have non-subject refinements like
$\mathsf{clinical{\text{-}}care}/\mathsf{billing}$ (administrative
billing is a sub-purpose of care, not equivalent to it). These are
not used in the core corpus but are available for fixture extensions.
Treat them as refinements below the root, incomparable to subject
refinements unless explicitly composed (see §3).

**Compound refinements.** $\mathsf{clinical{\text{-}}care}/
\mathsf{patient{\text{=}}alice}/\mathsf{billing}$ is below both
$\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$ and
$\mathsf{clinical{\text{-}}care}/\mathsf{billing}$. Compound
refinements compose by string concatenation in code; semantically
they sit at the meet of their components.

---

## 3. Join semantics

Join $\sqcup$ returns the least element at-or-above all operands:

- $p \sqcup p = p$.
- $p \sqcup \top = \top$.
- $p \sqcup q$ for incomparable $p, q$ in different roots = $\top$.
- $p \sqcup q$ for incomparable $p, q$ under the same root = the root.
  Example: $\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}
  \sqcup \mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}bob} =
  \mathsf{clinical{\text{-}}care}$. **This is the case the purpose-
  binding contribution turns on:** the join of two patient-bound
  purposes is the unrefined root, not either patient. A capability at
  $\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$
  is **not** at-or-below the join of two patient purposes, so the
  consistency check fails.
- $p \sqcup q$ where $p \le q$ = $q$.

Implement in `capguard/purpose_lattice.py` as:

```python
def join(p: Purpose, q: Purpose) -> Purpose:
    if p == q: return p
    if p == TOP or q == TOP: return TOP
    if leq(p, q): return q
    if leq(q, p): return p
    # incomparable: walk up to least common ancestor
    return least_common_ancestor(p, q)
```

`least_common_ancestor` returns the root if both operands are under
the same root; $\top$ otherwise.

---

## 4. Worked examples

These are the examples Claude Code should be able to compute correctly
before the lattice code is considered done.

**Example 1 — purpose attenuation, valid.**
Capability: $\kappa.\mathsf{Purp} =
\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$.
Justifying data: a single record with
$L^{\text{purp}}(d) = \mathsf{clinical{\text{-}}care}/
\mathsf{patient{\text{=}}alice}$.
Join over justifying data: $\mathsf{clinical{\text{-}}care}/
\mathsf{patient{\text{=}}alice}$.
Check: $\kappa.\mathsf{Purp} \le \text{join}$? Yes.
**Verdict: purpose-consistent.**

**Example 2 — purpose-boundary violation (the headline case).**
Capability: $\kappa.\mathsf{Purp} =
\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$.
Justifying data: two records, one with
$L^{\text{purp}}(d_1) = \mathsf{clinical{\text{-}}care}/
\mathsf{patient{\text{=}}alice}$, one with
$L^{\text{purp}}(d_2) = \mathsf{clinical{\text{-}}care}/
\mathsf{patient{\text{=}}bob}$.
Join over justifying data: $\mathsf{clinical{\text{-}}care}$ (the root,
since alice and bob are incomparable refinements).
Check: is $\mathsf{clinical{\text{-}}care}/
\mathsf{patient{\text{=}}alice} \le \mathsf{clinical{\text{-}}care}$? Yes.
**Verdict: purpose-consistent.**
But the attack: tool call's *target* is patient bob, not alice. The
authority-flow check catches this because $L^{\text{auth}}(a) =
\{\mathsf{bob}\}$ and the capability is $\kappa.P = \mathsf{alice}$.

This example shows authority and purpose can be combined to catch the
attack even when each alone is insufficient. The key is that for the
purpose-binding *headline* attack to succeed against authority-only
defenses, the authority must be consistent — see Example 3.

**Example 3 — purpose-boundary violation, authority consistent (the
real headline).**
Setup: a doctor's agent has capability
$\kappa.P = \mathsf{doctor}$, $\kappa.\mathsf{Purp} =
\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$.
The doctor is the legitimate authority for both alice's and bob's
records (e.g., it's their primary care physician). The records both
have $L^{\text{auth}}(d) = \{\mathsf{doctor}\}$ — the doctor's
authority is what was used to read them.
Justifying data: alice's record (purpose: care/alice) and bob's
record (purpose: care/bob).
Join over justifying data: $\mathsf{clinical{\text{-}}care}$.
Authority check: $\kappa.P = \mathsf{doctor} \in L^{\text{auth}}(a) =
\{\mathsf{doctor}\}$. Passes.
Purpose check: $\kappa.\mathsf{Purp} =
\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice} \le
\mathsf{clinical{\text{-}}care}$. Passes.
But: the tool call's effect is on patient bob, not alice. The
capability was issued for alice's care, not bob's. This is a purpose-
boundary violation in spirit but passes the formal check. **This is
the case where the lattice as specified is insufficient** — see §5.

**Example 4 — fixed via subject-binding refinement on the
invocation.**
The fix: capability's purpose stays at
$\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}alice}$.
Tool argument $a$ targeting patient bob is parsed and the targeted
subject is extracted as a structural label on $a$:
$\mathsf{subject}(a) = \mathsf{bob}$. Purpose check is augmented:
$\kappa.\mathsf{Purp}$'s subject (alice) must equal $\mathsf{subject}(a)$
(bob). Mismatch → fail.

Equivalently, in the calculus: extend `justify(a)` to include the
target as a synthetic datum with purpose
$\mathsf{clinical{\text{-}}care}/\mathsf{patient{\text{=}}bob}$. Then
the join becomes $\mathsf{clinical{\text{-}}care}$ but the capability
is at a strict refinement, so $\kappa.\mathsf{Purp} \le \text{join}$
holds (passes), which is wrong.

This shows the join-and-attenuate semantics alone don't catch
Example 3. The lattice provides the formal structure, but the
*consistency predicate* in `policy_purpose.py` must additionally check
**subject equality on subject-bound capabilities**: if
$\kappa.\mathsf{Purp}$ has a subject refinement, then either
$\mathsf{subject}(a)$ must equal $\kappa.\mathsf{Purp}$'s subject, or
$\kappa.\mathsf{Purp}$ must be the root (subjectless).

This is the load-bearing semantic refinement and must be in
`policy_purpose.py`. It is not just lattice ordering; it is a
predicate over the lattice with subject-extraction from invocations.
Document this in the paper as the formal mechanism that distinguishes
purpose-bound capabilities from data-flow control.

---

## 5. Subject extraction from tool calls

`policy_purpose.py` requires `subject(a)` for tool calls whose
capability has a subject-bound purpose. Subject extraction is per-tool
and lives in a config table:

| Tool | Subject extraction |
|---|---|
| `gmail.send_message(to, ...)` | `subject = to` |
| `gmail.read_message(id)` | `subject = author_principal_of(id)` |
| `drive.share_with(file_id, principal)` | `subject = principal` |
| `drive.delete_file(file_id)` | `subject = author_principal_of(file_id)` |
| `payments.commit_payment(recipient, ...)` | `subject = recipient` |
| `calendar.create_event(attendees, ...)` | `subject = attendees` (set; require all to match or fail) |

Subject extraction is deterministic and does not depend on the LLM.
It is a property of the tool, not of the agent's reasoning. The
extraction table lives in `capguard/purpose_lattice.py` alongside the
matching logic.

---

## 6. Conservative over-approximation for unlabeled data

If a datum reaches the agent's context without a purpose label (e.g.,
a tool returned data the mock server forgot to label, or a datum
synthesized by the agent itself with no clear lineage), the
conservative over-approximation is to label it $\top$.

**Implication:** any tool call justified by such a datum requires a
capability at $\top$ to pass the purpose check. Capabilities are
typically issued at strictly-below-$\top$ purposes, so unlabeled data
effectively poisons the call. This is intentional. Soundness over
precision: better to fail-closed on unknown provenance than to
silently allow.

This is the empirical price the paper documents in `EMPIRICAL_DESIGN.md`
§6: in practice, the agent occasionally synthesizes facts that have no
direct substring match to any labeled span, the propagator falls back
to "join of recent reads" (per CLAUDE.md §13), and FPR rises on
benign workloads with heavy paraphrasing. This is the tradeoff curve
the paper reports.

---

## 7. Lattice extensions

To extend the lattice for new fixture domains:

1. Update this document. Add the new root or refinement, specify its
   ordering relations, and update the join examples.
2. Update `capguard/purpose_lattice.py` to match.
3. Update `THEOREMS.md` only if the extension affects the proof
   structure (it usually does not, since the proofs are
   parameterized over $\Pi$).
4. Update fixtures' `axes.json` files to use the new purposes if
   relevant.

Do not extend the lattice for a single fixture's convenience. The
lattice's value to the paper is its fixedness; ad-hoc additions
weaken the contribution.

---

## 8. Lattice in code (skeleton)

```python
# capguard/purpose_lattice.py

from dataclasses import dataclass
from typing import Optional, FrozenSet

@dataclass(frozen=True)
class Purpose:
    root: str               # 'clinical-care' | 'financial-advisory' | 'operations'
    subject: Optional[str]  # principal id or None
    sub: Optional[str]      # 'billing' etc, or None
    is_top: bool = False

TOP = Purpose(root='', subject=None, sub=None, is_top=True)

def leq(p: Purpose, q: Purpose) -> bool:
    if q.is_top: return True
    if p.is_top: return False
    if p.root != q.root: return False
    # q is at-or-above p iff q's refinements are a subset
    if q.subject is not None and q.subject != p.subject: return False
    if q.sub is not None and q.sub != p.sub: return False
    return True

def join(p: Purpose, q: Purpose) -> Purpose:
    if leq(p, q): return q
    if leq(q, p): return p
    if p.root != q.root: return TOP
    # same root, incomparable refinements
    return Purpose(root=p.root, subject=None, sub=None)

def subject_consistent(cap_purp: Purpose, invocation_subject: Optional[str]) -> bool:
    if cap_purp.is_top: return True
    if cap_purp.subject is None: return True  # capability not subject-bound
    return invocation_subject == cap_purp.subject
```

This is the implementation `policy_purpose.py` consumes. It is small
on purpose; the framework's contribution is conceptual, not in
algorithmic complexity.

---

End of PURPOSE_LATTICE.md.
