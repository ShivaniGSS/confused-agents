from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdaptiveAttacker:
    strategy: str
    budget: int
    turn_count: int = 0
    observations: list[dict[str, Any]] = field(default_factory=list)

    def next_mutation(self, turn: dict[str, Any], defense_verdict: str) -> dict[str, Any] | None:
        self.observations.append({"turn": turn.get("turn"), "defense_verdict": defense_verdict})
        self.turn_count += 1
        if self.turn_count >= self.budget:
            return None
        if self.strategy == "escalating_rephrase" and defense_verdict == "block":
            return {"attack_hint": "rephrase_more_benignly"}
        if self.strategy == "axis_switching" and defense_verdict == "block":
            return {"attack_hint": "switch_axis"}
        return None
