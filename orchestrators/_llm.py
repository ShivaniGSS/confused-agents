"""LLM client abstraction + Anthropic / scripted implementations + cache.

The abstraction is a single function:

    chat(messages, tools, model, settings) -> AssistantTurn

where AssistantTurn carries the assistant's response in a normalized form:
either a final text reply or one or more tool calls.

Caching: LLM responses are cached on disk in `results/llm_cache/`,
keyed by hash of (provider, model, messages, tools, settings). This is
required by CLAUDE.md Section 11: "Cache LLM responses in
`results/llm_cache/` keyed by hash of (prompt, model, settings) so
repeat runs don't re-bill."

Determinism: `temperature=0` is the only supported setting. Hard rule 7
(no silent fallbacks) is enforced — provider errors and unknown model
names raise.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol


# ---------- Normalized data model ----------

@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict
    server: str
    method: str


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class AssistantTurn:
    """A single turn produced by the LLM. Either text-only (final answer)
    or contains one or more tool calls, possibly interleaved with text.
    """
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # provider-specific payload, kept for the audit log
    # Normalized token usage when the provider returns it (OpenAI: prompt/completion;
    # Anthropic: input/output). Omitted for scripted / cache misses.
    usage: dict[str, Any] | None = None

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


# ---------- Cache ----------

class LLMCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, payload: dict[str, Any]) -> str:
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def get(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        p = self.root / f"{self._key(payload)}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def put(self, payload: dict[str, Any], response: dict[str, Any]) -> None:
        p = self.root / f"{self._key(payload)}.json"
        p.write_text(json.dumps(response, separators=(",", ":"), sort_keys=True))


# ---------- Client protocol ----------

class LLMClient(Protocol):
    name: str  # "anthropic" | "together" | "scripted"

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDef],
        model: str,
        system_prompt: str,
        cache: Optional[LLMCache] = None,
    ) -> AssistantTurn:
        ...


# ---------- Anthropic client ----------

class AnthropicClient:
    """Anthropic Messages API with tool use. Requires ANTHROPIC_API_KEY."""

    name = "anthropic"

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for AnthropicClient")
        # Lazy import; SDK pulls in network deps.
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages, tools, model, system_prompt, cache=None):
        anthro_tools = [
            {
                "name": t.name.replace(".", "__"),  # Anthropic tool names: [a-zA-Z0-9_-]
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        cache_payload = {
            "provider": self.name,
            "model": model,
            "system": system_prompt,
            "messages": messages,
            "tools": anthro_tools,
            "temperature": 0.0,
        }
        if cache is not None:
            hit = cache.get(cache_payload)
            if hit is not None:
                return _from_anthropic_payload(hit, tools)
        resp = self._client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.0,
            system=system_prompt,
            tools=anthro_tools,
            messages=messages,
        )
        payload = {
            "stop_reason": resp.stop_reason,
            "content": [_anthropic_content_to_dict(c) for c in resp.content],
            "usage": {
                "input_tokens": getattr(resp.usage, "input_tokens", None),
                "output_tokens": getattr(resp.usage, "output_tokens", None),
            },
        }
        if cache is not None:
            cache.put(cache_payload, payload)
        return _from_anthropic_payload(payload, tools)


def _anthropic_content_to_dict(c) -> dict[str, Any]:
    if c.type == "text":
        return {"type": "text", "text": c.text}
    if c.type == "tool_use":
        return {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
    return {"type": c.type, "raw": str(c)}


def _from_anthropic_payload(payload: dict[str, Any], tools: list[ToolDef]) -> AssistantTurn:
    name_map = {t.name.replace(".", "__"): t.name for t in tools}
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for c in payload["content"]:
        if c["type"] == "text":
            text_parts.append(c["text"])
        elif c["type"] == "tool_use":
            canonical = name_map.get(c["name"], c["name"])
            tool_calls.append(ToolCall(id=c["id"], name=canonical, args=c.get("input", {})))
    usage = payload.get("usage")
    return AssistantTurn(
        text="".join(text_parts), tool_calls=tool_calls, raw=payload, usage=usage
    )


# ---------- Together AI client (OpenAI-compatible) ----------

class TogetherClient:
    """Together AI chat completions with tool use (OpenAI-compatible API)."""

    name = "together"

    def __init__(self) -> None:
        api_key = os.environ.get("TOGETHER_API_KEY")
        if not api_key:
            raise RuntimeError("TOGETHER_API_KEY is required for TogetherClient")
        import together
        self._client = together.Together(api_key=api_key)

    def chat(self, messages, tools, model, system_prompt, cache=None):
        oa_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name.replace(".", "__"),
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        oa_messages = [{"role": "system", "content": system_prompt}, *messages]
        cache_payload = {
            "provider": self.name,
            "model": model,
            "messages": oa_messages,
            "tools": oa_tools,
            "temperature": 0.0,
        }
        if cache is not None:
            hit = cache.get(cache_payload)
            if hit is not None:
                return _from_openai_payload(hit, tools)
        resp = self._client.chat.completions.create(
            model=model,
            messages=oa_messages,
            tools=oa_tools,
            temperature=0.0,
            max_tokens=4096,
        )
        choice = resp.choices[0]
        msg = choice.message
        usage_obj = getattr(resp, "usage", None)
        usage: dict[str, Any] | None = None
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
            }
        payload = {
            "finish_reason": choice.finish_reason,
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in (msg.tool_calls or [])
            ],
            "usage": usage,
        }
        if cache is not None:
            cache.put(cache_payload, payload)
        return _from_openai_payload(payload, tools)


class OpenAIClient:
    """OpenAI chat completions with tool use."""

    name = "openai"

    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIClient")
        import httpx
        import openai
        from openai import DefaultHttpxClient

        # SDK default is connect=5s, which often fails on slow TLS or captive proxies.
        read_s = float(os.environ.get("OPENAI_HTTP_READ_TIMEOUT", "600"))
        connect_s = float(os.environ.get("OPENAI_HTTP_CONNECT_TIMEOUT", "60"))
        timeout = httpx.Timeout(timeout=read_s, connect=connect_s)
        trust_env = os.environ.get("OPENAI_HTTPX_TRUST_ENV", "1").lower() not in (
            "0",
            "false",
            "no",
        )
        if trust_env:
            self._client = openai.OpenAI(api_key=api_key, timeout=timeout)
        else:
            http_client = DefaultHttpxClient(timeout=timeout, trust_env=False)
            self._client = openai.OpenAI(api_key=api_key, http_client=http_client)

    def chat(self, messages, tools, model, system_prompt, cache=None):
        oa_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name.replace(".", "__"),
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        oa_messages = [{"role": "system", "content": system_prompt}, *messages]
        cache_payload = {
            "provider": self.name,
            "model": model,
            "messages": oa_messages,
            "tools": oa_tools,
            "temperature": 0.0,
        }
        if cache is not None:
            hit = cache.get(cache_payload)
            if hit is not None:
                return _from_openai_payload(hit, tools)
        resp = self._client.chat.completions.create(
            model=model,
            messages=oa_messages,
            tools=oa_tools,
            temperature=0.0,
            max_tokens=4096,
        )
        choice = resp.choices[0]
        msg = choice.message
        usage_obj = getattr(resp, "usage", None)
        usage: dict[str, Any] | None = None
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
            }
        payload = {
            "finish_reason": choice.finish_reason,
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in (msg.tool_calls or [])
            ],
            "usage": usage,
        }
        if cache is not None:
            cache.put(cache_payload, payload)
        return _from_openai_payload(payload, tools)


def _from_openai_payload(payload: dict[str, Any], tools: list[ToolDef]) -> AssistantTurn:
    name_map = {t.name.replace(".", "__"): t.name for t in tools}
    tool_calls: list[ToolCall] = []
    for tc in payload.get("tool_calls", []):
        try:
            args = json.loads(tc["arguments"]) if isinstance(tc["arguments"], str) else tc["arguments"]
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM emitted malformed JSON for tool {tc['name']}: {e}")
        canonical = name_map.get(tc["name"], tc["name"])
        tool_calls.append(ToolCall(id=tc["id"], name=canonical, args=args))
    return AssistantTurn(
        text=payload.get("content", ""),
        tool_calls=tool_calls,
        raw=payload,
        usage=payload.get("usage"),
    )


# ---------- Scripted client (for tests / harness wiring without API keys) ----------

@dataclass
class ScriptedStep:
    """One turn in a scripted conversation. Either a list of tool_calls
    (each {name, args}) or a final `text`.
    """
    tool_calls: list[dict[str, Any]] | None = None
    text: str | None = None


class ScriptedClient:
    """Replays a fixed sequence of assistant turns. Used to exercise the
    harness wiring deterministically without an LLM provider key.
    """

    name = "scripted"

    def __init__(self, steps: list[ScriptedStep]) -> None:
        self._steps = list(steps)
        self._i = 0

    def chat(self, messages, tools, model, system_prompt, cache=None):
        if self._i >= len(self._steps):
            raise RuntimeError("ScriptedClient exhausted; no more scripted turns")
        step = self._steps[self._i]
        self._i += 1
        if step.tool_calls is not None:
            calls = [
                ToolCall(id=f"scr_{self._i}_{j}", name=tc["name"], args=tc.get("args", {}))
                for j, tc in enumerate(step.tool_calls)
            ]
            return AssistantTurn(
                text=step.text or "",
                tool_calls=calls,
                raw={"scripted": True, "step": self._i},
                usage=None,
            )
        return AssistantTurn(
            text=step.text or "",
            tool_calls=[],
            raw={"scripted": True, "step": self._i},
            usage=None,
        )


# ---------- Factory ----------

def make_client(provider: str | None = None) -> LLMClient:
    p = (provider or os.environ.get("PROVIDER", "anthropic")).lower()
    if p == "anthropic":
        return AnthropicClient()
    if p == "together":
        return TogetherClient()
    if p == "openai":
        return OpenAIClient()
    raise ValueError(f"unknown provider: {p!r} (expected 'anthropic', 'together', or 'openai')")
