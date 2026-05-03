# Corpus contract (`scenarios.json`)

This file defines how scenarios relate to evaluation claims.

## Invariants

1. **Stable ids** — Each scenario has a unique `id` (path-style string). Reports and traces key off this id.
2. **Axis label** — `axis` is a single letter A–L matching the stress dimensions in `docs/citation_ready_framework.md` and `harness/coverage_matrix.py`.
   - **I** — Complementarity scenarios: CapGuard routing stays on-subject but integrity, CaMeL-style plan/recipient binding, or trajectory drift may still block.
   - **J** — Cross-tenant data leakage (real incidents: Asana, Supabase, Salesforce 2025). Two variants: `no_provenance` (universal gap — all defenses miss) and `with_provenance` (integrity_only / camel_style catch when per-record labels are available via FIDES-style infrastructure).
   - **K** — Indirect injection via tool response (real incidents: EchoLeak CVE-2025-32711, GitHub MCP hijack). Two variants: `naive` (off-subject routing; CapGuard also catches) and `onsubject` (injected instruction routes on-subject; only spotlighting catches, demonstrating its unique value).
   - **L** — Cross-session memory/state contamination (SnailSploit 2025). The memory system does not propagate injection flags across sessions, so all current defenses miss — a documented architectural gap.
3. **Attack trace** — `turns` describes the intended attack trajectory. Tool entries may set `violation: true` when the action exceeds the capability boundary.
4. **Benign twin** — `benign_turns` provides a same-length control with violations removed or redirected to the approved subject. The harness may derive benign turns when absent (see `harness/multi_turn_runner.py`).
5. **Capability and tools** — `capability.purpose` encodes the authorized subject; `approved_tools` lists the tool surface for that scenario. Optional **`camel_contract_tools`** narrows the CaMeL approved plan while the agent still sees the full `approved_tools` list (typical pattern: omit a tool from the contract so `not_in_plan` can fire on an otherwise on-subject call).

6. **Simulated provenance for defenses** — Tool call objects in `turns` / `benign_turns` may include **`response_provenance`**: a map from datum id to `{ "principal", optional "authorized_readers" }` merged into the harness’s simulated tool response so `integrity_only` and `camel_style` see labels even when mock RPC fails (e.g. missing drive id).

7. **Simulated injection metadata** — Tool call objects in `turns` / `benign_turns` may include **`response_metadata`**: a dict merged into the simulated tool response alongside provenance. Supported keys:
   - `contains_user_content` (bool) — This tool returned user-generated content (emails, issues, documents). `SpotlightingDefense` records this flag.
   - `injection_detected` (bool) — A spotlighting classifier detected adversarial instruction content in the response. `SpotlightingDefense` sets its internal injection flag and blocks all subsequent consequential actions.
   Neither flag is set for tools that return system-internal data (e.g. agent memory context); that absence is what makes axis-L scenarios a gap: memory reads look trusted to the defense stack.

8. **Optional adaptive fields** — `attacker_strategy` and `attacker_budget` apply only to axis E; other scenarios omit them.

9. **Tool parameter completeness (live LLMs)** — Mock servers require full arguments for some tools (for example `calendar.create_event` needs ISO `start`/`end`, `attendees`, and `description`; `gmail.send_message` should include `subject`). The orchestrator normalizes common omissions before RPC so defenses still evaluate **post-normalization** behavior consistently. Prefer explicit fields in `scenarios.json` for readability.

10. **Live vs scripted** — With `--live-llm`, `harness/multi_turn_runner.py` wraps each turn in capability-binding and schema reminders so frontier models complete multi-step tool trajectories; scripted replay is unchanged.

11. **`user_prompt` on every turn (live LLM)** — For `--live-llm`, each object in `turns` and `benign_turns` **must** include a **`user_prompt`**: a natural-language user-facing task (not an internal step label). The harness prefers `user_prompt` over `agent_reasoning` when building the message to the model; `agent_reasoning` remains author documentation. CI runs `scripts/validate_scenario_prompts.py` (and `tests/test_scenario_prompts.py`). `run_matrix` asserts the same catalog before any paid API calls unless `SKIP_LIVE_PROMPT_VALIDATION=1` or `--skip-live-prompt-validation` is set (debug only). To re-apply the canonical prompt strings from the generator, run `python3 scripts/_generate_scenarios_with_user_prompts.py` (writes `scenarios/.scenarios.json.bak` first).

## Versioning

- Treat `scenarios/scenarios.json` as a versioned artifact: cite the git revision when publishing numbers.
- Structural constraints are summarized in `scenario_metadata.schema.json` (validation is optional but recommended for forks).

## Pairing rule

For each scenario, **attack** and **benign** runs share the same `scenario_id`, `axis`, and `defense` cell; they differ only in `run_type` in `summary.jsonl`. Metrics that compare attack vs. benign behavior assume this pairing.

## CapGuard routing convention (benign twins)

**CapGuard** (`defenses/capguard.py`) compares the capability subject parsed from `capability.purpose` (e.g. `alice` from `clinical-care/patient=alice`) to an extracted **target** from each attempted tool call: for `gmail.send_message`, the local-part of `arguments.to` before `@`; for `payments.commit_payment`, `arguments.recipient`; for `drive.share_with`, `arguments.principal`; see `harness/multi_turn_runner.py` (`_target_subject_from_call`).

Benign scripted calls **must** use addresses and ids whose extracted target **equals** that capability subject (e.g. `alice@clinic.test`, `phoenix@corp.test` for `operations/project=phoenix`). Aliases such as `alice_care@…` or `alice_records@…` are **not** equivalent under this rule and inflate **false-positive rate** for CapGuard / full_stack without representing “real” overblocking.

**Live LLM caveat:** The harness surfaces each turn’s task from `user_prompt` if set, else `agent_reasoning`. Vague benign prompts (e.g. “send to legitimate backup”) can cause the model to **invent** a recipient whose local-part is not the capability subject; CapGuard then blocks and FPR looks high even though the **scripted** `tool_calls` were aligned. Prefer an explicit `user_prompt` that names the exact `to` address when measuring routing FPR.

Documented benign violations of this rule are considered **corpus bugs**; remaining FPR after alignment is treated as a limitation of binary subject equality (see paper / run reports).

## Reporting: scenario-first

Axis-level rollups (A–H) are **secondary**. Primary tables and narrative should use **`scenario_id`** (per-scenario cells in `summary.jsonl` and generated `RUN_REPORT.md`) so elicitation and defense effects are not averaged away.

## Elicitation metadata

Scenarios may include **`elicitation`** with optional fields:

- **`strength`** — `strong` | `medium` | `weak`: how aggressively each turn’s `user_prompt` pins ids, recipients, and next-step intent. **Stratify** paper tables or appendix sensitivity on this when mixing adaptive (E) with fully pinned scenarios.
- **`live_llm_profile`** / **`paper_note`** — Free-text guidance for interpretation (e.g. adaptive attacker, high refusal).

Treat high refusal as a **model-safety / pressure-test** finding; defense comparisons that require executed attacks should cite **`detection_rate_given_attack_executed`** in `defense_landscape_matrix.json` and refusal rates, not raw `detection_rate` alone.

## Axis H: injection vs routing

`metric_decomposition` on axis H scenarios separates **whether the model complied with poisoned tool/schema signals** from **whether CapGuard blocked on subject binding** when email sends occur. Do not attribute routing blocks to “detecting injection.”
