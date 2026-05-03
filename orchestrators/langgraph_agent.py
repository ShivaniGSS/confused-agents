"""LangGraph-based orchestrator using StateGraph (LangGraph >= 1.0 API).

Exposes the same tool surface as ``minimal_agent.py`` but routes the
reasoning loop through LangGraph's ``StateGraph`` / ``ToolNode`` pattern
instead of the hand-rolled ReAct loop.  Both orchestrators emit identical
JSONL log shapes so the harness can score them mechanically.

Defense policy
--------------
``tool_policy`` is injected at the tool-execution layer.  When it returns
``{"verdict": "block"}`` the tool function short-circuits without touching
the RPC server and returns a structured error.  The attempt is still logged
so the harness scoring loop sees it.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import httpx

from mock_mcp._common import JsonlLogger
from .minimal_agent import AgentRunConfig, AgentRunResult, ServerEndpoint, effective_system_prompt
from ._tools import all_tools, by_name


class LangGraphUnavailable(RuntimeError):
    """Raised when LangGraph cannot be imported or wired for the configured provider."""


def _import_langgraph():
    try:
        from langgraph.graph import StateGraph, END  # noqa: F401
        from langchain_core.messages import HumanMessage  # noqa: F401
    except Exception as exc:
        raise LangGraphUnavailable(f"langgraph/langchain unavailable: {exc}")


def _build_chat_model(provider: str, model: str):
    """Return a LangChain chat model configured at temperature=0."""
    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except Exception as exc:
            raise LangGraphUnavailable(f"langchain_anthropic missing: {exc}")
        return ChatAnthropic(model=model, temperature=0.0, max_tokens=4096)
    if provider == "together":
        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise LangGraphUnavailable(f"langchain_openai missing: {exc}")
        import os
        return ChatOpenAI(
            model=model,
            temperature=0.0,
            max_tokens=4096,
            base_url="https://api.together.xyz/v1",
            api_key=os.environ.get("TOGETHER_API_KEY"),
        )
    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise LangGraphUnavailable(f"langchain_openai missing: {exc}")
        import os
        return ChatOpenAI(
            model=model,
            temperature=0.0,
            max_tokens=4096,
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
    raise LangGraphUnavailable(f"unsupported provider {provider!r} for LangGraph orchestrator")


def _make_lc_tool(tdef, endpoint: ServerEndpoint, principal: str, logger: JsonlLogger,
                   run_id: str, step_counter: list[int], tool_policy=None):
    """Wrap an MCP RPC behind a LangChain tool.

    If ``tool_policy`` is provided it is called with (tool_name, kwargs) before
    the RPC; a ``{"verdict": "block"}`` response short-circuits execution and
    returns a structured error the agent sees as a tool result.
    """
    from langchain_core.tools import StructuredTool
    import inspect

    method = tdef.method
    server = tdef.server

    def _impl(**kwargs) -> str:
        step = step_counter[0]
        step_counter[0] = step + 1
        tool_call_id = f"lg_{step}"
        logger.write({
            "kind": "tool_call",
            "run_id": run_id,
            "step": step,
            "tool_call_id": tool_call_id,
            "tool": tdef.name,
            "server": server,
            "method": method,
            "principal": principal,
            "args": kwargs,
        })
        # Defense policy interposition.
        if tool_policy is not None:
            policy_result = tool_policy(tdef.name, kwargs)
            if policy_result and policy_result.get("verdict") == "block":
                reason = policy_result.get("reason", "blocked by policy")
                logger.write({
                    "kind": "tool_result", "run_id": run_id, "step": step,
                    "tool_call_id": tool_call_id, "tool": tdef.name,
                    "blocked": True, "block_reason": reason,
                })
                return json.dumps({"error": f"blocked: {reason}"})
        try:
            r = httpx.post(
                endpoint.url,
                json={"method": method, "params": kwargs, "principal": principal},
                timeout=15.0,
            )
            if r.status_code != 200:
                err = r.json().get("error", r.text)
                raise RuntimeError(f"RPC {method} -> {r.status_code}: {err}")
            body = r.json()
            if body.get("error"):
                raise RuntimeError(f"RPC {method} server error: {body['error']}")
        except Exception as exc:
            logger.write({
                "kind": "tool_result", "run_id": run_id, "step": step,
                "tool_call_id": tool_call_id, "tool": tdef.name, "error": str(exc),
            })
            return json.dumps({"error": str(exc)})
        logger.write({
            "kind": "tool_result", "run_id": run_id, "step": step,
            "tool_call_id": tool_call_id, "tool": tdef.name,
            "result": body.get("result"), "provenance": body.get("provenance"),
        })
        return json.dumps({"result": body.get("result")})

    # Build a StructuredTool so LangGraph knows the schema.
    # Use the canonical dot-name as the tool name (LangChain strips dots internally).
    return StructuredTool.from_function(
        func=_impl,
        name=tdef.name.replace(".", "__"),
        description=tdef.description,
        return_direct=False,
    )


def run_agent(
    *,
    prompt: str,
    config: AgentRunConfig,
    provider: str,
    endpoints: dict[str, ServerEndpoint],
    tool_policy=None,
) -> AgentRunResult:
    """Run a LangGraph StateGraph ReAct agent against the harness tool surface."""
    _import_langgraph()

    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
    from typing import Annotated
    try:
        from typing import TypedDict
    except ImportError:
        from typing_extensions import TypedDict

    logger = JsonlLogger(config.log_path)
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    system_prompt = effective_system_prompt(config.system_prompt, provider)
    logger.write({
        "kind": "agent_start",
        "run_id": run_id,
        "principal": config.principal,
        "model": config.model,
        "provider": f"langgraph:{provider}",
        "system_prompt": system_prompt,
        "user_prompt": prompt,
        "tools": [t.name for t in config.tools],
    })

    step_counter = [0]
    lc_tools = [
        _make_lc_tool(t, endpoints[t.server], config.principal, logger, run_id, step_counter,
                      tool_policy=tool_policy)
        for t in config.tools
    ]
    lc_tools_by_name = {t.name: t for t in lc_tools}
    chat_model = _build_chat_model(provider, config.model).bind_tools(lc_tools)

    class AgentState(TypedDict):
        messages: Annotated[list, add_messages]

    def call_model(state: AgentState) -> dict:
        response = chat_model.invoke(state["messages"])
        return {"messages": [response]}

    def call_tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        results = []
        for tc in getattr(last, "tool_calls", []):
            tool_name = tc["name"]
            tool_args = tc.get("args", {})
            tool_fn = lc_tools_by_name.get(tool_name)
            if tool_fn is None:
                result_content = json.dumps({"error": f"unknown tool {tool_name!r}"})
            else:
                result_content = tool_fn.invoke(tool_args)
            results.append(ToolMessage(
                content=result_content,
                tool_call_id=tc["id"],
                name=tool_name,
            ))
        return {"messages": results}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", call_tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    app = graph.compile()

    init_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]
    result = app.invoke(
        {"messages": init_messages},
        config={"recursion_limit": 2 * config.max_iter},
    )

    final_text = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            content = m.content
            final_text = content if isinstance(content, str) else str(content)
            break

    logger.write({
        "kind": "agent_end",
        "run_id": run_id,
        "final_text": final_text,
        "iterations": step_counter[0],
        "exit_reason": "final",
    })

    # Reconstruct tool_call summary from the JSONL log.
    summary: list[dict[str, Any]] = []
    for line in Path(config.log_path).read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("kind") == "tool_result" and rec.get("run_id") == run_id:
            args = _last_args_for_call(config.log_path, run_id, rec.get("tool_call_id"))
            tool_raw = rec.get("tool", "")
            summary.append({
                "tool": tool_raw,
                "args": args,
                "server": tool_raw.split(".")[0] if tool_raw else None,
                "method": tool_raw.split(".")[-1] if tool_raw else None,
                "provenance": rec.get("provenance"),
                "blocked": rec.get("blocked", False),
                "block_reason": rec.get("block_reason"),
                "executed": not rec.get("blocked", False),
            })

    return AgentRunResult(
        run_id=run_id,
        final_text=final_text,
        iterations=step_counter[0],
        exit_reason="final",
        tool_calls=summary,
    )


def _last_args_for_call(log_path: str, run_id: str, tool_call_id: str) -> dict[str, Any]:
    for line in Path(log_path).read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if (rec.get("kind") == "tool_call"
                and rec.get("run_id") == run_id
                and rec.get("tool_call_id") == tool_call_id):
            return rec.get("args", {})
    return {}
