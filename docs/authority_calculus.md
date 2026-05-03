# Authority calculus

Mirrors Section 4 of the paper. The CapGuard implementation modules
(`capguard/capability.py`, `capguard/provenance.py`, `capguard/policy.py`,
`capguard/irreversibility.py`) must conform to these definitions
exactly.

## Capability

$\kappa = (P, \mathsf{Auth}, \mathsf{Purp}, \tau)$ where:

* $P$ is the issuing principal id.
* $\mathsf{Auth}$ is the set of permitted operations (tool ids the holder may invoke).
* $\mathsf{Purp}$ is a purpose label drawn from a lattice $(\Pi, \le)$.
* $\tau$ is the validity window $(\tau_{\text{from}}, \tau_{\text{to}})$.

## Delegation

$\kappa_1 \rightsquigarrow \kappa_2$ requires all four:

1. **Authority narrowing** — $\kappa_2.\mathsf{Auth} \subseteq \kappa_1.\mathsf{Auth}$.
2. **Purpose narrowing** — $\kappa_2.\mathsf{Purp} \le \kappa_1.\mathsf{Purp}$.
3. **Validity narrowing** — $\tau(\kappa_2) \subseteq \tau(\kappa_1)$.
4. **Holder constraint** — the principal of $\kappa_2$ holds $\kappa_1$ at delegation time.

## Authority-flow label

$L^{\text{auth}}(d) \subseteq \mathcal{P}$ is the set of principals
whose authority the system is willing to exercise on the basis of
datum $d$. Labels propagate through reasoning:

$$L^{\text{auth}}(f(d_1, \dots, d_k)) = \bigcup_i L^{\text{auth}}(d_i)$$

CapGuard approximates this propagation at runtime by substring
matching outgoing tool-call argument bytes against recently-returned
labelled spans (a sound but imprecise over-approximation; see
`capguard/provenance.py` for the trade-off discussion).

## Authority-consistent invocation

A tool call $T_j(a)$ is authority-consistent iff the presented
capability $\kappa_j$ satisfies:

1. **Principal in argument labels** — $\kappa_j.P \in L^{\text{auth}}(a)$.
2. **Purpose dominates justifying data** — $\kappa_j.\mathsf{Purp} \le \bigsqcup_{d \in \mathsf{justify}(a)} \mathsf{Purp}(d)$,

where $\mathsf{justify}(a)$ is the set of data items in the agent's
context motivating the invocation.

## Confused-deputy attack

An authority-inconsistent invocation. CapGuard's job is to detect and
block these at the proxy layer, before the call reaches the underlying
mock MCP server (and a fortiori before any irreversible action commits).

## Irreversibility-aware tightening

For tools tagged `irreversible` (see `capguard/irreversibility.py`
defaults: `gmail.send_message`, `payments.commit_payment`), the
authority-consistency predicate is tightened: any $L^{\text{auth}}$
label other than the invoking principal triggers either a hard block
or a synthetic user-confirmation step. This is the commit-race
pre-invocation defense.

## Theorem 1 (runtime-only impossibility)

The paper claims that a defense relying on runtime detection alone
(without provenance labels) cannot pre-empt a confused-deputy attack
on irreversible operations. The corresponding ablation in the
artifact is "CapGuard with provenance disabled" (run via
`harness.run_corpus` after editing `capguard/provenance.py` to
return empty label sets). Expected: ASR rises toward baseline.
