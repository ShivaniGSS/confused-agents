from __future__ import annotations

from typing import Any

from defenses.base import Decision, Defense


class SpotlightingDefense(Defense):
    """
    AgentDojo-style input marking / spotlighting defense.

    Tracks whether any prior tool response contained user-generated content
    (flagged via ``response_metadata.contains_user_content``) AND whether a
    spotlighting classifier detected an injection attempt
    (``response_metadata.injection_detected``).

    On any consequential tool call after an injection was detected, block.
    This fires independently of CapGuard's routing check: the injected
    instruction may produce on-subject routing that CapGuard allows.
    """

    name = "spotlighting"

    CONSEQUENTIAL_TOOLS = {
        "gmail.send_message",
        "drive.share_with",
        "drive.delete_file",
        "calendar.create_event",
        "calendar.delete_event",
        "payments.commit_payment",
    }

    def __init__(self) -> None:
        self.user_content_seen: bool = False
        self.injection_detected: bool = False
        self._injection_source: str = ""

    def reset(self) -> None:
        self.user_content_seen = False
        self.injection_detected = False
        self._injection_source = ""

    def on_tool_response(self, tool_call: dict[str, Any], tool_response: dict[str, Any]) -> None:
        meta = tool_response.get("response_metadata") or {}
        if not isinstance(meta, dict):
            return
        if meta.get("contains_user_content"):
            self.user_content_seen = True
        if meta.get("injection_detected"):
            self.injection_detected = True
            self._injection_source = str(tool_call.get("tool", ""))

    def check(self, tool_call: dict[str, Any], history, turn, context_state) -> Decision:
        tool_name = tool_call.get("tool", "")
        if tool_name not in self.CONSEQUENTIAL_TOOLS:
            return Decision(verdict="allow", reason="read-only tool")
        if self.injection_detected:
            return Decision(
                verdict="block",
                mechanism="injection_signal_detected",
                reason=(
                    f"spotlighting: injection detected in prior response from "
                    f"{self._injection_source!r}; blocking consequential action {tool_name!r}"
                ),
                metadata={
                    "user_content_seen": self.user_content_seen,
                    "injection_source": self._injection_source,
                },
            )
        return Decision(
            verdict="allow",
            reason="no injection signal observed",
            metadata={"user_content_seen": self.user_content_seen},
        )
