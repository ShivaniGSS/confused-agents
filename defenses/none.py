from __future__ import annotations

from defenses.base import Decision, Defense


class NoDefense(Defense):
    name = "none"

    def check(self, tool_call, history, turn, context_state):
        return Decision(verdict="allow")
