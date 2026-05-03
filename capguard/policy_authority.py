from __future__ import annotations

from .capability import Capability
from .policy_types import PolicyDecision


def check_authority(
    *,
    capability: Capability,
    tool: str,
    arg_labels: set[str],
) -> PolicyDecision:
    if capability.principal not in arg_labels:
        return PolicyDecision(
            allowed=False,
            reason=f"capability_principal_not_in_arg_labels:{capability.principal}",
        )
    return PolicyDecision(allowed=True, reason="authority_consistent")
