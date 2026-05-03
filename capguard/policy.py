"""Composed policy with runtime ablation modes."""

from __future__ import annotations

from .capability import Capability
from .policy_authority import check_authority
from .policy_purpose import check_purpose
from .policy_types import PolicyDecision


def check(
    *,
    capability: Capability,
    tool: str,
    args: dict,
    arg_labels: set[str],
    purpose_join: str,
    mode: str = "both",
) -> PolicyDecision:
    """Modes: both | authority_only | purpose_only | off."""
    if tool not in capability.permitted_tools:
        return PolicyDecision(allowed=False, reason=f"tool_not_in_capability:{tool}")
    if mode == "off":
        return PolicyDecision(allowed=True, reason="policy_off")
    if mode == "authority_only":
        return check_authority(capability=capability, tool=tool, arg_labels=arg_labels)
    if mode == "purpose_only":
        return check_purpose(
            capability=capability,
            tool=tool,
            args=args,
            purpose_join=purpose_join,
        )
    if mode == "both":
        a = check_authority(capability=capability, tool=tool, arg_labels=arg_labels)
        if not a.allowed:
            return a
        p = check_purpose(
            capability=capability,
            tool=tool,
            args=args,
            purpose_join=purpose_join,
        )
        if not p.allowed:
            return p
        return PolicyDecision(allowed=True, reason="authority_and_purpose_consistent")
    raise ValueError(f"unknown policy mode: {mode!r}")
