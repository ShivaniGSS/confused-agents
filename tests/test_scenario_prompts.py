from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.scenario_prompt_validation import assert_catalog_live_user_prompts

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_catalog_has_live_user_prompts() -> None:
    p = REPO_ROOT / "scenarios" / "scenarios.json"
    assert_catalog_live_user_prompts(json.loads(p.read_text()))


def test_validation_fails_on_short_user_prompt() -> None:
    bad = {
        "scenarios": [
            {
                "id": "test/x",
                "turns": [{"turn": 1, "user_prompt": "short", "tool_calls": []}],
                "benign_turns": [{"turn": 1, "user_prompt": "x" * 50, "tool_calls": []}],
            }
        ]
    }
    with pytest.raises(ValueError, match="Live LLM scenario prompt validation failed"):
        assert_catalog_live_user_prompts(bad)
