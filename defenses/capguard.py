from __future__ import annotations

from defenses.base import Decision, Defense


def _extract_subject(purpose: str) -> str:
    if "=" in purpose:
        return purpose.split("=")[-1].strip()
    return purpose.strip()


class CapGuardDefense(Defense):
    name = "capguard"

    def __init__(self, capability_purpose: str):
        self.capability_purpose = capability_purpose
        self.capability_subject = _extract_subject(capability_purpose)

    def check(self, tool_call, history, turn, context_state):
        target = tool_call.get("target_subject")
        if not target:
            return Decision(verdict="allow", reason="no target subject extracted")
        if str(target) != self.capability_subject:
            return Decision(
                verdict="block",
                mechanism="purpose_subject_mismatch",
                reason=f"cap.subject={self.capability_subject} != target={target}",
            )
        return Decision(verdict="allow")
