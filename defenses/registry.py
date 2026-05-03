from __future__ import annotations

from defenses.base import Defense
from defenses.camel_style import CaMeLStyleDefense
from defenses.capguard import CapGuardDefense
from defenses.full_stack import FullStackDefense
from defenses.integrity_only import IntegrityOnlyDefense
from defenses.model_safety import ModelSafetyDefense
from defenses.none import NoDefense
from defenses.spotlighting import SpotlightingDefense
from defenses.trajectory_monitor import TrajectoryMonitor


STACK_LAYER_ORDER: tuple[str, ...] = (
    "spotlighting",
    "integrity_only",
    "camel_style",
    "capguard",
    "trajectory_monitor",
)


def make_stack_layer_defenses(
    *,
    invoking_principal: str,
    capability_purpose: str,
    camel_plan: frozenset[str],
) -> dict[str, Defense]:
    """Single shared instances per run.

    Order: spotlighting → integrity → camel → cap → trajectory.
    Spotlighting fires first: injection-detected blocks before routing is checked,
    so it can catch on-subject injections that CapGuard would allow.
    """
    return {
        "spotlighting": SpotlightingDefense(),
        "integrity_only": IntegrityOnlyDefense(invoking_principal),
        "camel_style": CaMeLStyleDefense(invoking_principal, camel_plan),
        "capguard": CapGuardDefense(capability_purpose),
        "trajectory_monitor": TrajectoryMonitor(capability_purpose),
    }


DEFENSE_NAMES = (
    "none",
    "model_safety",
    "spotlighting",
    "integrity_only",
    "camel_style",
    "capguard",
    "trajectory_monitor",
    "full_stack",
)


def make_defense(
    name: str,
    *,
    invoking_principal: str,
    capability_purpose: str,
    approved_plan: set[str] | frozenset[str],
) -> Defense:
    if name == "none":
        return NoDefense()
    if name == "model_safety":
        return ModelSafetyDefense()
    if name == "integrity_only":
        return IntegrityOnlyDefense(invoking_principal)
    if name == "camel_style":
        return CaMeLStyleDefense(invoking_principal, approved_plan)
    if name == "spotlighting":
        return SpotlightingDefense()
    if name == "capguard":
        return CapGuardDefense(capability_purpose)
    if name == "trajectory_monitor":
        return TrajectoryMonitor(capability_purpose)
    if name == "full_stack":
        layers = make_stack_layer_defenses(
            invoking_principal=invoking_principal,
            capability_purpose=capability_purpose,
            camel_plan=frozenset(approved_plan),
        )
        return FullStackDefense(layers)
    raise ValueError(f"unknown defense {name!r}")
