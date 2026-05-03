from __future__ import annotations

import json
from typing import Any

from defenses.base import Decision, Defense


class CaMeLStyleDefense(Defense):
    name = "camel_style"

    def __init__(self, invoking_principal: str, approved_plan: set[str] | frozenset[str]):
        self.invoking_principal = invoking_principal
        self.approved_plan = frozenset(approved_plan)
        self.cap_tags: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        self.cap_tags = {}

    def on_tool_response(self, tool_call: dict[str, Any], tool_response: dict[str, Any]) -> None:
        prov = tool_response.get("provenance") or {}
        if not isinstance(prov, dict):
            return
        for datum_id, datum_prov in prov.items():
            if isinstance(datum_prov, dict):
                self.cap_tags[datum_id] = {
                    "principal": datum_prov.get("principal"),
                    "authorized_readers": datum_prov.get(
                        "authorized_readers",
                        [datum_prov.get("principal"), self.invoking_principal],
                    ),
                }

    def check(self, tool_call, history, turn, context_state):
        tool_name = tool_call.get("tool", "")
        args = tool_call.get("arguments", {})
        if self.approved_plan and tool_name not in self.approved_plan:
            return Decision(
                verdict="block",
                mechanism="not_in_plan",
                reason=f"{tool_name} not in approved plan",
            )

        recipient = None
        if tool_name == "gmail.send_message":
            recipient = args.get("to")
        elif tool_name == "drive.share_with":
            recipient = args.get("principal")

        if recipient:
            blob = json.dumps(args, sort_keys=True)
            attributed = [d for d in self.cap_tags if d in blob]
            for datum_id in attributed:
                readers = set(self.cap_tags.get(datum_id, {}).get("authorized_readers", []))
                if readers and recipient not in readers:
                    return Decision(
                        verdict="block",
                        mechanism="unauthorized_recipient",
                        reason=f"{recipient} not authorized for {datum_id}",
                    )

        return Decision(verdict="allow", reason="in plan / recipient allowed")
