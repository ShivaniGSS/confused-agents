from __future__ import annotations

from defenses.base import Decision, Defense

# Keep in sync with `STACK_LAYER_ORDER` in `defenses/registry.py` (avoid importing registry: circular).
_STACK_ORDER = ("spotlighting", "integrity_only", "camel_style", "capguard", "trajectory_monitor")


class FullStackDefense(Defense):
    name = "full_stack"

    def __init__(self, defenses: dict[str, Defense]):
        self.defenses = defenses

    def on_tool_response(self, tool_call, tool_response):
        for name in _STACK_ORDER:
            d = self.defenses.get(name)
            if d is not None:
                d.on_tool_response(tool_call, tool_response)

    @staticmethod
    def synthesize(layer_decisions: dict[str, Decision]) -> Decision:
        """Compose stack verdict from per-layer checks (each layer.check called exactly once elsewhere)."""
        all_decisions = {k: layer_decisions[k] for k in _STACK_ORDER if k in layer_decisions}
        blockers = [(name, d) for name, d in all_decisions.items() if d.verdict == "block"]
        if blockers:
            name, dec = blockers[0]
            return Decision(
                verdict="block",
                mechanism=f"full_stack:{name}:{dec.mechanism}",
                reason=dec.reason,
                metadata={
                    "all_decisions": {
                        k: {
                            "verdict": v.verdict,
                            "mechanism": v.mechanism,
                            "reason": v.reason,
                        }
                        for k, v in all_decisions.items()
                    },
                    "first_blocking_layer": name,
                },
            )
        return Decision(
            verdict="allow",
            reason="all stack layers allow",
            metadata={
                "all_decisions": {
                    k: {
                        "verdict": v.verdict,
                        "mechanism": v.mechanism,
                        "reason": v.reason,
                    }
                    for k, v in all_decisions.items()
                }
            },
        )

    def check(self, tool_call, history, turn, context_state):
        layer_decisions = {
            name: self.defenses[name].check(tool_call, history, turn, context_state)
            for name in _STACK_ORDER
            if name in self.defenses
        }
        return self.synthesize(layer_decisions)
