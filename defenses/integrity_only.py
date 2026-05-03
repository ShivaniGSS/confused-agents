from __future__ import annotations

import json
from typing import Any

from defenses.base import Decision, Defense


class IntegrityOnlyDefense(Defense):
    name = "integrity_only"

    CONSEQUENTIAL_TOOLS = {
        "gmail.send_message",
        "drive.share_with",
        "drive.delete_file",
        "calendar.create_event",
        "calendar.delete_event",
        "payments.commit_payment",
    }

    def __init__(self, invoking_principal: str):
        self.invoking_principal = invoking_principal
        self.data_labels: dict[str, str] = {}

    def on_tool_response(self, tool_call: dict[str, Any], tool_response: dict[str, Any]) -> None:
        prov = tool_response.get("provenance") or {}
        if not isinstance(prov, dict):
            return
        for datum_id, datum_prov in prov.items():
            principal = ""
            if isinstance(datum_prov, dict):
                principal = str(datum_prov.get("principal", ""))
            elif isinstance(datum_prov, str):
                principal = datum_prov
            self.data_labels[datum_id] = (
                "trusted" if principal == self.invoking_principal else "untrusted"
            )

    def check(self, tool_call, history, turn, context_state):
        tool_name = tool_call.get("tool", "")
        if tool_name not in self.CONSEQUENTIAL_TOOLS:
            return Decision(verdict="allow", reason="read-only tool")

        args_blob = json.dumps(tool_call.get("arguments", {}), sort_keys=True)
        untrusted = [
            datum_id
            for datum_id, lbl in self.data_labels.items()
            if lbl == "untrusted" and datum_id in args_blob
        ]
        if untrusted:
            return Decision(
                verdict="block",
                mechanism="integrity_violation",
                reason=f"untrusted data in consequential args: {sorted(untrusted)}",
            )
        return Decision(verdict="allow", reason="all attributed data trusted")
