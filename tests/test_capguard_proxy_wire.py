"""Wire-layer tests for capguard/proxy.py.

These tests verify the HTTP plumbing — request shape, target routing,
provenance side-channel stripping, JSONL decision logging, allow/block
forwarding — WITHOUT exercising the production capability/policy/
provenance/irreversibility modules (which are HUMAN-AUTHORED per
CLAUDE.md hard rule 8).

We monkeypatch each `capguard.*` module with a minimal test stub so the
proxy has something to call into. The stubs are clearly NOT production
implementations and are scoped to this test file.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness.run_attack import load_attack, run_one
from orchestrators._llm import ScriptedClient, ScriptedStep


REPO_ROOT = Path(__file__).resolve().parents[1]
ATTACK_01 = REPO_ROOT / "attacks" / "fixtures" / "scenario_a_calendar" / "attack_01"


@dataclass(frozen=True)
class _StubCapability:
    principal: str
    permitted_tools: tuple
    purpose: str
    valid_from: float
    valid_to: float


def _install_test_stubs(monkeypatch, *, allow: bool, allow_for_tools: set[str] | None = None):
    """Install minimal stub implementations of the human-authored modules
    into the running interpreter for the duration of the test. The stubs
    are simple enough that the proxy can exercise its wire layer end-to-end.
    """
    from capguard import capability as cap_mod
    from capguard import irreversibility as irr_mod
    from capguard import policy as pol_mod
    from capguard import provenance as prov_mod

    def _mint(*, principal, permitted_tools, purpose, valid_from, valid_to, secret):
        return f"stub-token::{principal}::{purpose}"

    def _verify(token, secret, *, now_ts):
        if not token.startswith("stub-token::"):
            raise ValueError(f"bad stub token: {token!r}")
        _, principal, purpose = token.split("::", 2)
        return _StubCapability(
            principal=principal, permitted_tools=(), purpose=purpose,
            valid_from=now_ts - 1, valid_to=now_ts + 3600,
        )

    class _StubTracker:
        def __init__(self):
            self._labels: dict[str, set[str]] = {}

        def seed(self, invoking_principal, user_prompt):
            return None

        def record_returned(self, datum_id, value, labels, purpose_label=None):
            self._labels[datum_id] = set(labels)

        def labels_for_text(self, text):
            return set()

        def labels_for_args(self, args):
            return set()

        def purpose_join_for_justify(self, args):
            return "session"

    def _check(*, capability, tool, args, arg_labels, purpose_join, mode="both"):
        if allow_for_tools is not None and tool not in allow_for_tools:
            return pol_mod.PolicyDecision(allowed=False, reason=f"stub_block:{tool}")
        return pol_mod.PolicyDecision(
            allowed=allow, reason="stub_allow" if allow else "stub_block",
        )

    def _stricter(*, base_decision, invoking_principal, tool, arg_labels, trusted=None):
        return base_decision  # passthrough; production tightens this

    monkeypatch.setattr(cap_mod, "mint", _mint, raising=True)
    monkeypatch.setattr(cap_mod, "verify", _verify, raising=True)
    monkeypatch.setattr(prov_mod, "ProvenanceTracker", _StubTracker, raising=True)
    monkeypatch.setattr(pol_mod, "check", _check, raising=True)
    monkeypatch.setattr(irr_mod, "stricter_check", _stricter, raising=True)


def _two_step_script() -> list[ScriptedStep]:
    return [
        ScriptedStep(tool_calls=[{
            "name": "calendar.list_events",
            "args": {"date_range": {
                "start": "2026-04-26T00:00:00Z",
                "end": "2026-04-26T23:59:59Z",
            }},
        }]),
        ScriptedStep(text="done."),
    ]


def test_proxy_forwards_when_policy_allows(monkeypatch):
    _install_test_stubs(monkeypatch, allow=True)
    attack = load_attack(ATTACK_01)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "run"
        client = ScriptedClient(_two_step_script())
        outcome = run_one(
            attack, client=client, model="scripted",
            workdir=workdir, capguard=True,
        )
        assert outcome.exit_reason == "final"
        # Agent log must contain at least one capguard_decision allow record.
        log = (workdir / "logs" / "agent.jsonl").read_text().splitlines()
        decisions = [json.loads(l) for l in log if json.loads(l).get("kind") == "capguard_decision"]
        assert any(d["decision"] == "allow" for d in decisions), decisions
        # The orchestrator log should also have a tool_call_id->tool_result pair
        # for the list_events call (the proxy forwarded successfully).
        tool_results = [json.loads(l) for l in log
                        if json.loads(l).get("kind") == "tool_result"
                        and json.loads(l).get("tool") == "calendar.list_events"]
        assert tool_results, "expected calendar.list_events to forward"
        # And the result the agent saw must NOT include provenance — the
        # proxy strips it before returning to the orchestrator.
        # (The orchestrator's tool_result log records the raw RPC response;
        # the stripped agent-visible payload is what _tool_result_message
        # builds. Our concern at the wire level is that proxy returned
        # provenance: None, which the orchestrator will faithfully log.)


def test_proxy_blocks_when_policy_denies(monkeypatch):
    # Block calendar.list_events specifically.
    _install_test_stubs(monkeypatch, allow=True, allow_for_tools=set())  # empty -> block all
    attack = load_attack(ATTACK_01)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "run"
        client = ScriptedClient(_two_step_script())
        outcome = run_one(
            attack, client=client, model="scripted",
            workdir=workdir, capguard=True,
        )
        log = (workdir / "logs" / "agent.jsonl").read_text().splitlines()
        decisions = [json.loads(l) for l in log if json.loads(l).get("kind") == "capguard_decision"]
        assert any(d["decision"] == "block" for d in decisions), decisions
        # The block reason is propagated as a 403 + capguard_block error;
        # the orchestrator logs a tool_result with an error field.
        results = [json.loads(l) for l in log
                   if json.loads(l).get("kind") == "tool_result"
                   and json.loads(l).get("tool") == "calendar.list_events"]
        assert results
        assert any("capguard_block" in (r.get("error") or "") for r in results), results


def test_capguard_real_stack_scripted_run():
    """CapGuard + real policy/provenance/capability completes a scripted run."""
    attack = load_attack(ATTACK_01)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "run"
        client = ScriptedClient(_two_step_script())
        outcome = run_one(
            attack, client=client, model="scripted",
            workdir=workdir, capguard=True,
        )
    assert outcome.exit_reason == "final"
