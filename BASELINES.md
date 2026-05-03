# BASELINES.md — Baseline implementations for comparison

This document specifies the two baselines CapGuard is compared against:
an integrity-only baseline approximating FIDES, and a CaMeL-like
baseline approximating Debenedetti et al.'s capability-system defense.

The baselines are not full reimplementations — they are faithful
approximations that capture the *labeling and policy semantics* of
their target systems. This document specifies what each baseline
implements, what it intentionally does not, and the reasoning. The
purpose is to defuse the reviewer pushback "your baselines are
strawmen."

---

## 1. Integrity-only baseline (`capguard/baselines/integrity_only.py`)

### Target system
FIDES (Costa et al., 2025): "Securing AI Agents with Information-Flow
Control." arxiv.org/abs/2505.23643.

### What we implement

A proxy that:
- Labels every datum returned from a mock-server tool with a binary
  `trusted` / `untrusted` label.
  - Data authored by the invoking principal $P_0$ is `trusted`.
  - Data authored by any other principal is `untrusted`.
- Propagates labels through tool-call arguments using **the same
  substring-matching propagation as CapGuard**. This is critical:
  propagation mechanism is held constant across the comparison so
  only the *labeling semantics* vary. Any difference in ASR or FPR
  between integrity-only and CapGuard is then attributable to the
  semantic difference, not to a propagation engineering difference.
- Blocks any tool call where any argument span carries the
  `untrusted` label, for tools tagged as "consequential" in the
  irreversibility config (any non-read-only tool).
- Permits all calls whose arguments are entirely `trusted`.

### What we intentionally do not implement

FIDES has additional machinery that is not part of the labeling
discipline we're isolating:
- **Variable passing and quarantined LLM**: FIDES routes risky tool
  outputs through variables and a quarantined LLM with constrained
  decoding. We do not implement this. **Why:** this machinery is
  FIDES's response to the labeling discipline's strictness — it
  preserves utility on data-dependent tasks. Including it in the
  baseline would conflate "integrity labels" with "variable routing,"
  and reviewers couldn't tell which mechanism is doing the work in any
  benign-workload comparison.
- **Confidentiality lattice**: FIDES has both integrity and
  confidentiality. We use only integrity. **Why:** the paper's
  contribution is about purpose, not confidentiality, and including
  confidentiality would require fixtures that test data-leak
  scenarios that aren't part of our threat model.
- **Selective hiding (the HIDE function)**: FIDES's mechanism for
  reducing context taint. **Why:** same reason as variable passing —
  it's a utility-preservation mechanism orthogonal to the labeling
  semantics.

### Faithfulness justification

The published FIDES evaluation reports that the *integrity-checking
component* of FIDES blocks attacks effectively but at utility cost on
benign workloads, with the variable-passing/quarantined-LLM mechanism
being what recovers utility. Our integrity-only baseline reproduces
the integrity-checking component without the utility-recovery
machinery. This is a faithful representation of "integrity-only
labeling discipline" — it does what FIDES's integrity dimension does
and does not pretend to be the full FIDES system. The paper's text
references this baseline as "FIDES-style integrity-only," not as
"FIDES."

### Predicted behavior

- Catches families A, B, C: external principal data is untrusted;
  consequential tools using untrusted data are blocked.
- Misses family D: all data is from trusted internal principals (the
  invoking principal has legitimate authority, the data is from
  patients/clients the doctor/advisor manages, all `trusted`).
  Integrity has nothing to say.
- Blocks B3 benign workload: legitimate cross-principal action uses
  data from external principals, which is `untrusted`, which blocks
  consequential tools. **This is the false-positive cell that
  demonstrates integrity-only's cost.**
- Pass on B4 benign: same-tenant data, all trusted; passes.

### Implementation skeleton

```python
# capguard/baselines/integrity_only.py

from capguard.proxy import BaseProxy
from capguard.provenance import propagate_labels  # shared with CapGuard

CONSEQUENTIAL_TOOLS = {"gmail.send_message", "drive.share_with",
                       "drive.delete_file", "calendar.create_event",
                       "payments.commit_payment"}

class IntegrityOnlyProxy(BaseProxy):
    def __init__(self, invoking_principal: str):
        self.p0 = invoking_principal
        self.label_map = {}  # datum_id -> 'trusted' | 'untrusted'

    def on_tool_response(self, tool_name, response):
        # Read provenance side channel; assign integrity label
        for datum_id, principal in response.provenance.items():
            self.label_map[datum_id] = (
                "trusted" if principal == self.p0 else "untrusted"
            )
        return response.strip_provenance()

    def on_tool_call(self, tool_name, args):
        labels = propagate_labels(args, self.label_map)
        if tool_name in CONSEQUENTIAL_TOOLS:
            if "untrusted" in labels:
                return self.block(reason=f"untrusted data in args to {tool_name}")
        return self.forward(tool_name, args)
```

Roughly 150 LOC including propagation glue and decision logging.

---

## 2. CaMeL-like baseline (`capguard/baselines/camel_like.py`)

### Target system
CaMeL (Debenedetti et al., 2025): "Defeating Prompt Injections by
Design." arxiv.org/abs/2503.18813.

### What we implement

A proxy plus a deterministic planner that:
- **Planner stage:** at session start, given the user's prompt, runs a
  deterministic plan extractor that produces a sequence of tool calls
  with capability tags. The planner is a hand-coded mapping from
  prompt patterns to plan templates — **it is not an LLM**. This is
  the most important implementation decision and is justified below.
- **Execution stage:** the proxy intercepts each tool call. Each call
  carries capability metadata derived from the planner stage:
  `provenance: principal who authored the data driving this call`,
  `readers: principals authorized to receive this data`. These are
  CaMeL's capability tags.
- **Policy stage:** before each tool call, check the policy table.
  Default policies (matching CaMeL's published defaults):
  - `gmail.send_message(to=X)`: pass iff `X ∈ readers` of any datum
    in argument provenance.
  - `drive.share_with(file, to=X)`: pass iff `X ∈ readers` of `file`'s
    provenance.
  - Read tools: always pass.
  - `payments.commit_payment(recipient=X, ...)`: pass iff `X` is
    pre-approved (a static allowlist in fixture config).
- **Result:** approximates CaMeL's "data-flow control via capability
  tags with policy enforcement at tool boundary."

### What we intentionally do not implement

- **Real planner via LLM.** CaMeL's planner is an LLM that emits a
  Python-like program. **We use deterministic plan templates instead.
  Why:** an LLM-based planner introduces a second LLM into the
  comparison, and any differences between CaMeL-like and CapGuard
  could be attributed to "the planner LLM made a different choice"
  rather than to the policy semantics. The deterministic planner
  isolates the policy-semantics comparison. The cost is that our
  CaMeL-like baseline is less general than CaMeL — it only handles
  fixtures whose plans we've templated. This is fine because we only
  evaluate on our 24-fixture corpus, and we template plans for each.
  Document this in the paper as an explicit faithfulness scope.
- **Quarantined LLM for parsing untrusted content.** CaMeL routes
  untrusted content through a separate LLM. **Same reason as above:**
  including a second LLM conflates labeling/policy semantics with LLM
  variation.
- **Custom Python interpreter.** CaMeL implements a Python subset
  interpreter. We don't. The deterministic plan templates are Python
  in name only — they're hand-coded callable objects. **Why:** the
  interpreter is engineering, not contribution; we're isolating the
  semantic claim that capability tags + policies catch attacks.

### Faithfulness justification

Per CaMeL's published evaluation, the policy-enforcement mechanism is
what catches attacks; the LLM planner extracts the data flow but
doesn't itself enforce. By using deterministic plan templates that
correctly model the data flow for each fixture (planner working
*correctly*), we give CaMeL-like the strongest possible interpretation:
its planner never makes mistakes. Any attacks the baseline misses are
attributable to the policy semantics being insufficient, not to
planner errors. **This is a strictly favorable comparison for the
baseline.**

The paper's text references this baseline as "CaMeL-style policy-
enforcement baseline" or "CaMeL-like" — never as "CaMeL."

### Predicted behavior

- Catches families A, B, C: data from external principals; policies
  block sending to wrong readers, sharing with wrong principals.
- Misses family D: data is all internally authored, all readers are
  legitimate (the doctor has authority for both alice and bob; the
  policy "send_message reader must be authorized" passes because bob
  is in the doctor's authority scope). The capability tag system has
  no notion of *purpose mismatch* — it tracks data flow, not why the
  capability was issued. **This is the load-bearing comparison cell.**
- Pass on B3 benign: legitimate cross-action's planner-template
  correctly identifies the cross-principal action and the policy
  permits because the user's prompt licensed it.
- May over-block on B4 benign: depending on how restrictive the
  policy table is for cross-subject reads. If our policy template is
  too restrictive, B4 ASR rises; document in the comparison.

### Implementation skeleton

```python
# capguard/baselines/camel_like.py

from capguard.proxy import BaseProxy

class PlanTemplate:
    """A hand-coded plan template matching a fixture's prompt."""
    def __init__(self, fixture_id: str):
        self.fixture_id = fixture_id
        # Each template specifies expected tool calls and capability tags.
        # Loaded from baselines/plan_templates/<fixture_id>.json

class CaMeLLikeProxy(BaseProxy):
    def __init__(self, invoking_principal: str, fixture_id: str):
        self.p0 = invoking_principal
        self.plan = PlanTemplate(fixture_id)
        self.cap_tags = {}  # datum_id -> {provenance, readers}

    def on_tool_response(self, tool_name, response):
        for datum_id, info in response.provenance.items():
            self.cap_tags[datum_id] = {
                "provenance": info["principal"],
                "readers": info.get("authorized_readers", [info["principal"], self.p0])
            }
        return response.strip_provenance()

    def on_tool_call(self, tool_name, args):
        # Look up policy for this tool
        policy = self.plan.policy_for(tool_name)
        # Get capability tags for argument provenance
        arg_provenance = self.compute_arg_provenance(args)
        # Apply policy
        if not policy.passes(args, arg_provenance, self.cap_tags):
            return self.block(reason=policy.violation_reason())
        return self.forward(tool_name, args)
```

Roughly 250 LOC including the policy table, plan templates for each
fixture, and provenance computation. Plan templates are JSON files in
`capguard/baselines/plan_templates/`.

If the templates-per-fixture approach is too much work, fallback:
implement one generic policy table that covers all fixtures and
accept slightly worse fidelity. Document the fallback in the paper.

---

## 3. What's negotiable on Day 6

If Day-5 budget pressure makes Day 6 tight:

### Tier 1 (must implement)
- Integrity-only baseline. ~150 LOC, straightforward.
- CaMeL-like baseline with **one generic policy table** instead of
  per-fixture plan templates. Reduces fidelity but keeps the
  comparison meaningful. ~150 LOC.

### Tier 2 (implement if time permits)
- CaMeL-like baseline with per-fixture plan templates.
- Quarantined-LLM-style variable passing (just as a sensitivity
  ablation, not the primary baseline).

### Tier 3 (skip without paper-level loss)
- LLM planner for CaMeL-like baseline (would conflate the comparison
  anyway).
- Confidentiality lattice for FIDES-like baseline (orthogonal).

The paper defends its baseline implementations in a "Faithfulness of
Baselines" subsection in §6 (Evaluation), which references this
document.

---

## 4. The ablation that uses the baselines

Per `EMPIRICAL_DESIGN.md` §6.3 Ablation 4, the headline comparison is:

|  | Family A | Family B | Family C | Family D | B3 | B4 |
|---|---|---|---|---|---|---|
| No defense | high | high | high | high | pass | pass |
| Integrity-only | low | low | low | **high** | **block** | pass |
| CaMeL-like | low | low | low | **high** | pass | maybe block |
| CapGuard auth-only | low | low | low | high | pass | pass |
| CapGuard purpose-only | high | high | high | **low** | pass | pass |
| CapGuard full | low | low | low | low | pass | pass |

Bolded cells are the contribution-defining cells. If empirical
results reproduce this pattern, the paper has a clean story. If they
deviate, the paper either reframes (e.g., "CaMeL-like did catch
family D because of a policy detail we didn't anticipate, here's
what that means") or surfaces the unexpected finding.

---

## 5. Citation discipline in the paper

When the paper references the baselines:

- "We compare CapGuard against an integrity-only labeling discipline
  approximating FIDES [Costa et al., 2025] and a capability-tagging
  discipline approximating CaMeL [Debenedetti et al., 2025]."
- "Our baselines isolate the labeling and policy semantics of these
  systems and do not reproduce all of their machinery; see
  `BASELINES.md` in the artifact for the faithfulness scope."
- Never write "we evaluate against FIDES" or "we evaluate against
  CaMeL" — those would be false. We evaluate against
  faithful approximations.

---

End of BASELINES.md.
