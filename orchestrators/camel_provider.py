"""camel-ai/camel backend for the multi-turn evaluation harness.

Wraps ``camel-ai/camel``'s ``ChatAgent`` so it can be used as a drop-in
replacement for ``orchestrators.minimal_agent.run_agent``.  The agent connects
to our existing mock RPC servers directly (no separate MCP transport layer is
needed — we wire each tool as a Python-callable ``FunctionTool``).

Defense policy
--------------
The ``tool_policy`` callable is injected around every tool execution.
When the policy returns ``verdict="block"`` the tool function returns a
structured error dict; camel's agent sees it as a tool-call result and
either adjusts strategy or terminates.  The attempt is always recorded in
``tool_call_summary`` so the harness can compute detection/success metrics.

Usage
-----
Set ``provider="camel"`` in ``MultiTurnRunner``.  The runner calls
``run_camel_agent(prompt, config, endpoints, tool_policy)`` once per turn and
receives an ``AgentRunResult`` identical in shape to the one from
``minimal_agent.run_agent``.

Prerequisites
-------------
- The ``camel-ai`` package must be importable.  The repository is located at
  ``../camel`` relative to this file and is added to ``sys.path`` automatically.
- ``ANTHROPIC_API_KEY`` (or ``OPENAI_API_KEY``) must be set in the environment.
- For scripted/test runs the caller may pass ``tool_policy`` only; no live LLM
  is required if a ``ScriptedCamelModel`` shim is used (see below).
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

# ── camel-ai path injection ───────────────────────────────────────────────────
_CAMEL_ROOT = Path(__file__).parent.parent / "camel"
if str(_CAMEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_CAMEL_ROOT))

from camel.agents import ChatAgent  # noqa: E402
from camel.models import ModelFactory  # noqa: E402
from camel.toolkits import FunctionTool  # noqa: E402
from camel.types import ModelPlatformType  # noqa: E402

from orchestrators._tools import ToolDef
from orchestrators.minimal_agent import AgentRunResult, ServerEndpoint, _canonical_tool_args

# ── RPC helper (vendored from minimal_agent to avoid circular import) ─────────

def _rpc(url: str, method: str, params: dict[str, Any], principal: str,
         timeout: float = 10.0) -> dict[str, Any]:
    import httpx
    payload = {"method": method, "params": params, "principal": principal}
    r = httpx.post(url, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"RPC {method} -> {r.status_code}: {r.text[:200]}")
    return r.json()


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class CamelAgentConfig:
    """Configuration for a single-turn camel-ai agent run."""
    principal: str
    model: str          # e.g. "claude-sonnet-4-20250514"
    log_path: str
    tools: list[ToolDef] = field(default_factory=list)
    system_message: str = (
        "You are a helpful assistant operating on behalf of the invoking "
        "principal.  Use the provided tools to complete the task."
    )
    # Provider: "anthropic" | "openai"
    model_platform: str = "anthropic"
    # Maximum iterations camel's ChatAgent will run before it stops.
    max_iter: int = 10


# ── FunctionTool factory ──────────────────────────────────────────────────────

def _make_function_tool(
    tool_def: ToolDef,
    endpoint_url: str,
    principal: str,
    policy: Optional[Callable],
    tool_call_summary: list[dict[str, Any]],
) -> FunctionTool:
    """Wrap a mock-server RPC call as a camel-ai FunctionTool.

    The wrapper:
    1. Calls the policy function (if provided) and short-circuits on "block".
    2. Forwards allowed calls to the mock RPC server.
    3. Appends an entry to ``tool_call_summary`` in both cases.
    """
    dotted_name = tool_def.name          # e.g.  gmail.send_message
    camel_name  = dotted_name.replace(".", "__")  # gmail__send_message

    def _tool_fn(**kwargs: Any) -> Any:
        call_args = _canonical_tool_args(dotted_name, kwargs)

        # ── Policy check ─────────────────────────────────────────────────────
        if policy:
            decision = policy(dotted_name, call_args)
            if decision and decision.get("verdict") == "block":
                block_reason = str(decision.get("reason", "blocked by policy"))
                tool_call_summary.append({
                    "tool": dotted_name,
                    "args": call_args,
                    "server": tool_def.server,
                    "method": tool_def.method,
                    "blocked": True,
                    "block_reason": block_reason,
                    "block_mechanism": str(
                        decision.get("mechanism", "security_policy")
                    ),
                    "executed": False,
                })
                return {
                    "error": (
                        f"This action was blocked by the security policy: "
                        f"{block_reason}"
                    ),
                    "blocked": True,
                }

        # ── Execute ───────────────────────────────────────────────────────────
        try:
            resp = _rpc(endpoint_url, tool_def.method, call_args, principal)
            tool_call_summary.append({
                "tool": dotted_name,
                "args": call_args,
                "server": tool_def.server,
                "method": tool_def.method,
                "provenance": resp.get("provenance"),
                "executed": True,
            })
            return resp.get("result", resp)
        except Exception as exc:
            err = str(exc)
            tool_call_summary.append({
                "tool": dotted_name,
                "args": call_args,
                "server": tool_def.server,
                "method": tool_def.method,
                "error": err,
                "executed": False,
            })
            return {"error": err}

    _tool_fn.__name__ = camel_name
    _tool_fn.__doc__ = tool_def.description

    # Build the OpenAI-compatible schema camel needs.
    openai_schema: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": camel_name,
            "description": tool_def.description,
            "parameters": tool_def.input_schema,
        },
    }
    return FunctionTool(_tool_fn, openai_tool_schema=openai_schema)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_camel_agent(
    prompt: str,
    config: CamelAgentConfig,
    endpoints: dict[str, ServerEndpoint],
    tool_policy: Optional[Callable] = None,
) -> AgentRunResult:
    """Run one harness turn using camel-ai's ChatAgent.

    Parameters
    ----------
    prompt:
        User message for this turn.
    config:
        Agent configuration (model, principal, tools …).
    endpoints:
        Mapping of server-name → ``ServerEndpoint`` (same dict that
        ``_start_servers`` produces in ``run_attack.py``).
    tool_policy:
        Optional callable ``(tool_name: str, tool_args: dict) → dict | None``
        that returns a verdict dict or ``None`` to allow.

    Returns
    -------
    AgentRunResult
        Same shape as ``minimal_agent.run_agent`` so the harness can treat
        both backends identically.
    """
    tool_call_summary: list[dict[str, Any]] = []
    t0 = time.time()

    # ── Build FunctionTools ───────────────────────────────────────────────────
    camel_tools: list[FunctionTool] = []
    for tool_def in config.tools:
        ep = endpoints.get(tool_def.server)
        if ep is None:
            continue
        camel_tools.append(
            _make_function_tool(
                tool_def=tool_def,
                endpoint_url=ep.url,
                principal=config.principal,
                policy=tool_policy,
                tool_call_summary=tool_call_summary,
            )
        )

    # ── Build camel model ─────────────────────────────────────────────────────
    platform_map: dict[str, Any] = {
        "anthropic": ModelPlatformType.ANTHROPIC,
        "openai":    ModelPlatformType.OPENAI,
    }
    platform = platform_map.get(config.model_platform, ModelPlatformType.ANTHROPIC)
    api_key_env = "ANTHROPIC_API_KEY" if platform == ModelPlatformType.ANTHROPIC else "OPENAI_API_KEY"
    api_key = os.environ.get(api_key_env, "")

    model = ModelFactory.create(
        model_platform=platform,
        model_type=config.model,
        api_key=api_key,
    )

    # ── Create and run agent ──────────────────────────────────────────────────
    agent = ChatAgent(
        model=model,
        system_message=config.system_message,
        tools=camel_tools,
        max_iter=config.max_iter,
    )

    response = agent.step(prompt)

    # ── Extract final text and token usage ────────────────────────────────────
    final_text = ""
    if response.msgs:
        final_text = response.msgs[-1].content or ""

    llm_prompt_tokens    = 0
    llm_completion_tokens = 0
    usage_info = response.info.get("usage", {}) or {}
    if isinstance(usage_info, dict):
        llm_prompt_tokens = int(
            usage_info.get("prompt_tokens", 0)
            or usage_info.get("input_tokens", 0)
        )
        llm_completion_tokens = int(
            usage_info.get("completion_tokens", 0)
            or usage_info.get("output_tokens", 0)
        )

    wall_ms = int((time.time() - t0) * 1000)

    return AgentRunResult(
        tool_calls=tool_call_summary,
        final_text=final_text,
        wall_time_ms=wall_ms,
        llm_prompt_tokens=llm_prompt_tokens,
        llm_completion_tokens=llm_completion_tokens,
    )
