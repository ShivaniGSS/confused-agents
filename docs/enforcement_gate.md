# Pre-execution enforcement gate

Defenses in this repo are evaluated as **gates on tool RPC**, not as post-hoc commentary on model text alone.

## API

`orchestrators/minimal_agent.run_agent(..., tool_policy=callable | None)`

The callable receives `(tool_name, tool_args)` before any HTTP call to a mock MCP server. It returns either:

- `None` — allow the call to proceed, or  
- A `dict` with at least:
  - `verdict`: `"allow"` or `"block"`
  - `reason`: human-readable string
  - `mechanism`: short defense identifier (aligned with `defenses/` modules)

When `verdict == "block"`, the orchestrator records the attempt as not executed and does not send the request to the server.

## Relation to metrics

- **Detection** is tied to the active defense emitting `block` before execution (see `harness/multi_turn_runner.py` and `detection_turn` in `summary.jsonl`).  
- **Attack success** requires a **violation** flag on the scenario tool call **and** `executed: true` after policy + model behavior.  
- **False positives** use **benign** runs: blocks on non-violating intended behavior.

For diagnostic comparison, `model_safety` classifies outcomes from assistant text and tool traces but does not replace the execution gate for the primary security metrics.
