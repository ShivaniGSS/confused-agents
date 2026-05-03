# Trace and audit schema

Two JSONL streams capture observability: **harness trace** (per tool attempt) and **agent log** (per LLM step).

## `trace.jsonl` (`harness/trace.py`)

Each line is a `TraceEntry` serialized with `dataclasses.asdict`:

| Field | Meaning |
| --- | --- |
| `run_id` | UUID-like id for this scenario × defense invocation |
| `turn` | Scenario turn index |
| `timestamp_ms` | Wall-clock ms (Unix) |
| `axis` | Scenario axis (A–H) |
| `scenario_id` | Stable id from `scenarios.json` |
| `agent_reasoning` | Scripted or logged reasoning text for the turn |
| `tool_call` | Normalized call: `tool`, `arguments`, `target_subject`, `violation`, `executed` |
| `tool_response` | Mock MCP response (`status`, `result` or `error`, `provenance`) |
| `context_state` | Harness snapshot (capability, history pointers, etc.) |
| `provenance_attribution` | Reserved for span-level attribution (often empty in mock runs) |
| `defense_decisions` | Map defense name → `{ verdict, mechanism, reason }` for **all** registered defenses |
| `persistent_state_changes` | Reserved for cross-session mutations |

**Attack success (harness)** is derived from summary rows: a violating, **executed** tool call in an attack run, consistent with `harness/multi_turn_runner.py`.

## Agent JSONL (`orchestrators/minimal_agent.py`)

Written under `runtime/.../agent_turn_*.jsonl`. Main `kind` values:

- `agent_start` — run id, config snapshot  
- `llm_call` — request metadata (no secrets)  
- `llm_response` — `text`, `tool_calls`, optional `usage` (provider token fields), `raw`  
- `llm_error` — provider failure  
- `tool_call` / `tool_result` — dispatch and MCP payload (provenance stripped before model sees it)  
- `agent_end` — final summary  

Token usage in `llm_response.usage` may include `prompt_tokens` / `completion_tokens` (OpenAI-style) or `input_tokens` / `output_tokens` (Anthropic-style). Scripted runs omit usage.
