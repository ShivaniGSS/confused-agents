from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Decision:
    verdict: str
    mechanism: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Defense:
    name = "defense"

    def on_tool_response(self, tool_call: dict[str, Any], tool_response: dict[str, Any]) -> None:
        return None

    def check(
        self,
        tool_call: dict[str, Any],
        history: list[dict[str, Any]],
        turn: dict[str, Any],
        context_state: dict[str, Any],
    ) -> Decision:
        raise NotImplementedError
