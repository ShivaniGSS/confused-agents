"""Validate observability scenarios for live LLM runs (natural-language user_prompts)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_MIN_USER_PROMPT_LEN = 40


def validate_scenario_live_user_prompts(
    scenario: dict[str, Any],
    *,
    min_len: int = DEFAULT_MIN_USER_PROMPT_LEN,
) -> list[str]:
    """
    Return a list of human-readable errors (empty if valid).
    Every turn in `turns` and `benign_turns` must have a non-trivial `user_prompt`
    so live runs do not surface developer-only `agent_reasoning` stubs as the task.
    """
    errors: list[str] = []
    sid = scenario.get("id", "?")
    for group_name in ("turns", "benign_turns"):
        turns = scenario.get(group_name) or []
        if not isinstance(turns, list):
            errors.append(f"{sid}: {group_name} must be a list")
            continue
        for t in turns:
            if not isinstance(t, dict):
                errors.append(f"{sid}: {group_name} entry must be an object")
                continue
            tnum = t.get("turn", "?")
            up = str(t.get("user_prompt", "")).strip()
            if len(up) < min_len:
                errors.append(
                    f"{sid} {group_name} turn {tnum}: `user_prompt` missing or shorter than "
                    f"{min_len} characters (live LLM needs a realistic user-facing task)."
                )
    return errors


def validate_catalog_live_user_prompts(
    payload: dict[str, Any],
    *,
    min_len: int = DEFAULT_MIN_USER_PROMPT_LEN,
) -> list[str]:
    out: list[str] = []
    for scenario in payload.get("scenarios", []):
        if not isinstance(scenario, dict):
            out.append("catalog: scenario entry must be an object")
            continue
        out.extend(validate_scenario_live_user_prompts(scenario, min_len=min_len))
    return out


def assert_catalog_live_user_prompts(
    payload: dict[str, Any],
    *,
    min_len: int = DEFAULT_MIN_USER_PROMPT_LEN,
) -> None:
    errs = validate_catalog_live_user_prompts(payload, min_len=min_len)
    if errs:
        raise ValueError(
            "Live LLM scenario prompt validation failed:\n"
            + "\n".join(f"  - {e}" for e in errs[:50])
            + ("\n  ..." if len(errs) > 50 else "")
        )


def load_and_assert_catalog(path: Path, *, min_len: int = DEFAULT_MIN_USER_PROMPT_LEN) -> None:
    import json

    payload = json.loads(path.read_text())
    assert_catalog_live_user_prompts(payload, min_len=min_len)
