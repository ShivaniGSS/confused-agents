"""Irreversibility-aware pre-invocation tightening."""

from __future__ import annotations

from typing import Literal

from .policy_types import PolicyDecision

ReversibilityTag = Literal["reversible", "bounded", "irreversible"]


TOOL_TAGS: dict[str, ReversibilityTag] = {
    "gmail.list_messages": "reversible",
    "gmail.read_message": "reversible",
    "gmail.send_message": "irreversible",
    "calendar.list_events": "reversible",
    "calendar.read_event": "reversible",
    "calendar.create_event": "reversible",
    "drive.list_files": "reversible",
    "drive.read_file": "reversible",
    "drive.list_comments": "reversible",
    "drive.share_with": "reversible",
    "drive.delete_file": "bounded",
    "drive.restore_file": "bounded",
    "payments.list_payments": "reversible",
    "payments.commit_payment": "irreversible",
}


def tag_for(tool: str) -> ReversibilityTag:
    if tool not in TOOL_TAGS:
        raise KeyError(f"no irreversibility tag registered for tool {tool!r}")
    return TOOL_TAGS[tool]


def stricter_check(
    *,
    base_decision: PolicyDecision,
    invoking_principal: str,
    tool: str,
    arg_labels: set[str],
    trusted: frozenset[str] | None = None,
) -> PolicyDecision:
    """Block **irreversible** tools when non-invoking principals taint args.

    Principals listed in ``trusted`` (fixture ``principals.trusted`` plus the
    invoking user) are not treated as dangerous foreign taint — benign tasks
    routinely quote or summarize mail/docs authored by colleagues.
    """
    if not base_decision.allowed:
        return base_decision
    tag = tag_for(tool)
    if tag != "irreversible":
        return base_decision
    tr = trusted if trusted is not None else frozenset({invoking_principal})
    foreign = {p for p in arg_labels if p != invoking_principal and p not in tr}
    if foreign:
        return PolicyDecision(
            allowed=False,
            reason=f"irreversible_foreign_principal:{sorted(foreign)}",
        )
    return base_decision
