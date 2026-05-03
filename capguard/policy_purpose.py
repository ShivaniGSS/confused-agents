from __future__ import annotations

from .capability import Capability
from . import purpose_lattice as pl
from .policy_types import PolicyDecision


def check_purpose(
    *,
    capability: Capability,
    tool: str,
    args: dict,
    purpose_join: str,
) -> PolicyDecision:
    if not purpose_join:
        return PolicyDecision(allowed=False, reason="empty_purpose_join")
    try:
        cap_p = pl.parse(capability.purpose)
        join_p = pl.parse(purpose_join)
    except ValueError as exc:
        return PolicyDecision(allowed=False, reason=f"purpose_error:{exc}")
    if not pl.leq(cap_p, join_p):
        return PolicyDecision(
            allowed=False,
            reason=f"purpose_inconsistent:cap={pl.serialize(cap_p)},join={pl.serialize(join_p)}",
        )
    inv_subject = pl.extract_invocation_subject(tool, args)
    if not pl.subject_consistent(cap_p, inv_subject):
        return PolicyDecision(
            allowed=False,
            reason="purpose_subject_mismatch",
        )
    return PolicyDecision(allowed=True, reason="purpose_consistent")
