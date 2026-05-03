# CapGuard: human-driven implementation guide

This artifact scaffolds wire protocol (`capguard/proxy.py`) and leaves
the paper’s core enforcement logic to you. Fill in the modules marked
**HUMAN-AUTHORED** so they match Section 4 (`docs/authority_calculus.md`)
and the threat model (`docs/threat_model.md`).

## What is already scaffolded

- `capguard/proxy.py` — HTTP interception, routing, capability verify hook,
  policy + irreversibility hooks, JSONL `capguard_decision` records,
  strips `provenance` before returning to the orchestrator.
- `capguard/irreversibility.py` — `TOOL_TAGS` defaults; you implement
  `stricter_check`.
- Tests can monkeypatch stubs to exercise the proxy without your policy.

## What you must implement

| File | Responsibility |
|------|----------------|
| `capguard/capability.py` | Mint / verify HMAC tokens; parse `κ`; `can_delegate`. |
| `capguard/purpose_lattice.py` | Finite Π, `≤`, `⊔`, optional datum→purpose mapping. |
| `capguard/provenance.py` | `ProvenanceTracker`: record tool results, substring (or better) propagation, optional `purpose_join_for_justify`. |
| `capguard/policy.py` | `check(...)`: principal ∈ L^auth(args) and purpose join constraint. |
| `capguard/irreversibility.py` | `stricter_check`: irreversible tools vs commit-race defense. |

## Wire contracts (keep aligned with mock servers)

- Upstream RPC responses: `{"result": ..., "provenance": {<id>: <principal>, ...}, "error": ...}`.
- The proxy records each **allowed** upstream response by serializing
  `result` to JSON and unioning all principals appearing in `provenance`
  into one labelled blob for substring matching (conservative). You may
  refine `ProvenanceTracker` to split per-datum fragments if you need
  tighter precision.
- Optional: implement `purpose_join_for_justify(self, args: dict) -> str`
  on the tracker; if present, the proxy passes it as `purpose_join` into
  `policy.check`. Otherwise `purpose_join` is the empty string and
  `policy.check` must derive justification purposes internally or reject.

## Checklist before declaring Day 5 done

- [ ] Every tool id in `irreversibility.TOOL_TAGS` matches the canonical
      `server.method` form the proxy uses.
- [ ] Block paths log a structured `reason` (no silent allow).
- [ ] Benign workload: zero unexpected blocks, or each block explained.
- [ ] At least one attack blocked with provenance/capability reason in JSONL.
- [ ] “Provenance disabled” ablation path documented (Theorem 1).

---

## Questions only you can answer (reply with decisions)

1. **Purpose lattice Π** — What are the atomic purpose labels in the paper
   (e.g. read-only vs send vs admin)? What is the Hasse diagram or rule
   for `≤`?

2. **Purp(d) for tool-returned data** — Is purpose derived only from the
   authoring principal, from fixture metadata, or from an explicit field
   in `provenance.json` per datum?

3. **justify(a)** — Operationally, is `justify(a)` exactly the set of
   recorded blobs that substring-match any argument string, or do you
   also include the user’s initial instruction as a separate labelled span?

4. **Delegation** — Does the evaluation mint a single session capability
   for P0 only, or do you model κ₁ ↝ κ₂ anywhere? If never, `can_delegate`
   can `raise NotImplementedError` or return False always — but say so in
   the paper.

5. **Irreversible stricter policy** — For `gmail.send_message` and
   `payments.commit_payment`, do you **hard-block** if
   `arg_labels \ {P0} ≠ ∅`, or implement a **synthetic confirmation**
   token path? If confirmation, how does the harness simulate it
   (second RPC, env flag)?

6. **Minimum fragment length** — What minimum length (bytes or graphemes)
   for substring matches to reduce noise? Document the soundness/precision
   trade-off you chose.

7. **Capability Auth vs tool names** — Exact set of strings in
   `permitted_tools`: bare `send_message` vs `gmail.send_message`?
   Must match what `policy.check` and the proxy’s `canonical_tool` use.

8. **Ablation: provenance off** — Mechanism: no-op tracker returning ∅
   for labels, or a harness flag? Either is fine if ASR rises toward
   baseline as predicted.

Once these are decided, implementation should be mechanical.
