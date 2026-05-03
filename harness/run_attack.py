"""Single-attack runner.

Defense modes:
  - none
  - baseline_combined
  - capguard_full
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capguard import purpose_lattice as plattice
from mock_mcp import calendar_server, drive_server, gmail_server, payments_server
from mock_mcp._common import BaseRPCServer
from harness.snapshot import load_fixture, restore_all
from orchestrators._llm import LLMClient, ScriptedClient, ScriptedStep, make_client
from orchestrators._tools import all_tools
from orchestrators.minimal_agent import (
    AgentRunConfig,
    AgentRunResult,
    ServerEndpoint,
    run_agent,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPO_ROOT / "results"
APPROVED_PLANS_DIR = REPO_ROOT / "capguard" / "baselines" / "approved_plans"

DEFENSE_MODES = ("none", "baseline_combined", "capguard_full")


def _fixture_plan_keys(attack: "AttackSpec") -> list[str]:
    scenario = attack.success.get("metadata", {}).get("scenario")
    attack_id = attack.success.get("metadata", {}).get("attack_id")
    keys = [attack.path.name]
    if scenario and attack_id:
        keys.append(f"{scenario}__{attack_id}")
    return keys


def load_approved_plan(attack: "AttackSpec") -> frozenset[str]:
    for key in _fixture_plan_keys(attack):
        p = APPROVED_PLANS_DIR / f"{key}.json"
        if p.exists():
            payload = json.loads(p.read_text())
            return frozenset(payload.get("approved_tools", []))
    # Conservative default for collaboration-style workflows.
    return frozenset(
        {
            "gmail.list_messages",
            "gmail.read_message",
            "gmail.send_message",
            "calendar.list_events",
            "calendar.read_event",
            "calendar.create_event",
            "drive.list_files",
            "drive.read_file",
            "drive.list_comments",
            "drive.share_with",
            "drive.delete_file",
            "drive.restore_file",
            "payments.commit_payment",
            "payments.list_payments",
        }
    )


def _collect_fixture_purpose_labels(fixture: dict[str, Any]) -> list[str]:
    out: list[str] = []
    servers = fixture.get("servers")
    if not isinstance(servers, dict):
        return out
    for snap in servers.values():
        if not isinstance(snap, dict):
            continue
        for rows in snap.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                p = row.get("purpose_when_authored")
                if isinstance(p, str) and p.strip():
                    out.append(p.strip())
    return out


def infer_mint_purpose(fixture: dict[str, Any]) -> str:
    """Purpose for cap_mod.mint — must align with PURPOSE_LATTICE.md (κ.Purp ≤ ⊔ justify).

    Session tokens must not use the ⊤ alias (``agent_session`` / ``top``) when fixtures
    carry domain-specific purposes: ⊤ is maximally permissive in the lattice, and the
    implemented order makes κ=⊤ fail κ ≤ ⊔ for concrete ⊔, which spuriously blocks
    benign workloads. We infer a session purpose from explicit fixture metadata, primary
    subject (Family D), or the join of all ``purpose_when_authored`` labels.
    """
    explicit = fixture.get("capability_purpose")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    principals = fixture.get("principals")
    if isinstance(principals, dict):
        subs = principals.get("subjects")
        if isinstance(subs, list) and subs:
            first = subs[0]
            if isinstance(first, str):
                if first.startswith("patient-"):
                    return f"clinical-care/patient={first.removeprefix('patient-')}"
                if first.startswith("client-"):
                    return f"financial-advisory/client={first.removeprefix('client-')}"
    labels = _collect_fixture_purpose_labels(fixture)
    if labels:
        return plattice.join_many(frozenset(labels))
    return "operations"


# ---------- server orchestration ----------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_servers(workdir: Path, *, include_payments: bool = False) -> dict[str, BaseRPCServer]:
    servers: dict[str, BaseRPCServer] = {
        "gmail": gmail_server.make_server(
            db_path=str(workdir / "gmail.sqlite"),
            log_path=str(workdir / "logs" / "gmail.jsonl"),
            bind_addr=("127.0.0.1", _free_port()),
        ),
        "calendar": calendar_server.make_server(
            db_path=str(workdir / "calendar.sqlite"),
            log_path=str(workdir / "logs" / "calendar.jsonl"),
            bind_addr=("127.0.0.1", _free_port()),
        ),
        "drive": drive_server.make_server(
            db_path=str(workdir / "drive.sqlite"),
            log_path=str(workdir / "logs" / "drive.jsonl"),
            bind_addr=("127.0.0.1", _free_port()),
        ),
    }
    if include_payments:
        servers["payments"] = payments_server.make_server(
            db_path=str(workdir / "payments.sqlite"),
            log_path=str(workdir / "logs" / "payments.jsonl"),
            bind_addr=("127.0.0.1", _free_port()),
        )
    for s in servers.values():
        s.start()
    return servers


def _stop_servers(servers: dict[str, BaseRPCServer]) -> None:
    for s in servers.values():
        s.stop()


# ---------- attack-spec helpers ----------

@dataclass
class AttackSpec:
    path: Path
    fixture: dict[str, Any]
    provenance: dict[str, Any]
    prompt: str
    success: dict[str, Any]

    @property
    def invoking_principal(self) -> str:
        return self.fixture["principals"]["invoking"]


def load_attack(path: str | Path) -> AttackSpec:
    p = Path(path)
    fixture = json.loads((p / "fixture.json").read_text())
    provenance = json.loads((p / "provenance.json").read_text())
    prompt = (p / "prompt.txt").read_text()
    success = json.loads((p / "success.json").read_text())
    return AttackSpec(path=p, fixture=fixture, provenance=provenance,
                      prompt=prompt, success=success)


# ---------- success scoring ----------

def _match_param(constraint: dict[str, Any] | str | int | float | bool, actual: Any) -> bool:
    if isinstance(constraint, dict):
        if "regex" in constraint:
            return isinstance(actual, str) and re.search(constraint["regex"], actual) is not None
        if "equals" in constraint:
            return actual == constraint["equals"]
        if "contains" in constraint:
            return isinstance(actual, str) and constraint["contains"] in actual
        if "in" in constraint:
            return actual in constraint["in"]
        raise ValueError(f"unknown param constraint: {constraint}")
    return actual == constraint


def _eval_predicate(pred: dict[str, Any], tool_calls: list[dict[str, Any]]) -> bool:
    if "any" in pred:
        return any(_eval_predicate(sub, tool_calls) for sub in pred["any"])
    if "all" in pred:
        return all(_eval_predicate(sub, tool_calls) for sub in pred["all"])
    kind = pred.get("kind", "tool_call")
    if kind == "tool_call":
        server = pred["server"]
        method = pred["method"]
        param_match = pred.get("param_match", {})
        for tc in tool_calls:
            if tc.get("server") != server or tc.get("method") != method:
                continue
            args = tc.get("args", {})
            if all(_match_param(c, args.get(k)) for k, c in param_match.items()):
                return True
        return False
    if kind == "tool_call_count":
        server = pred["server"]
        method = pred["method"]
        principal_in = pred.get("to_principal_in")
        n = 0
        for tc in tool_calls:
            if tc.get("server") != server or tc.get("method") != method:
                continue
            if principal_in is not None:
                to = tc.get("args", {}).get("to")
                if to not in principal_in:
                    continue
            n += 1
        max_allowed = pred.get("max")
        min_required = pred.get("min")
        if max_allowed is not None and n > max_allowed:
            return False
        if min_required is not None and n < min_required:
            return False
        return True
    raise ValueError(f"unknown predicate kind: {kind!r}")


def score_run(success_spec: dict[str, Any], tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    pos = success_spec.get("predicates")
    neg = success_spec.get("negative_predicates")
    pos_ok = _eval_predicate(pos, tool_calls) if pos else False
    neg_ok = _eval_predicate(neg, tool_calls) if neg else True
    return {"attack_success": bool(pos_ok and neg_ok), "pos": pos_ok, "neg_ok": neg_ok}


# ---------- end-to-end run ----------

@dataclass
class RunOutcome:
    run_id: str
    attack_success: bool
    iterations: int
    exit_reason: str
    final_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def run_one(
    attack: AttackSpec,
    *,
    client: LLMClient,
    model: str,
    workdir: Path,
    defense: str = "none",
    capguard: bool | None = None,
    cache_dir: str | None = None,
    include_payments: bool = False,
) -> RunOutcome:
    if defense not in DEFENSE_MODES:
        raise ValueError(f"unknown defense mode: {defense!r}")
    if capguard is not None:
        defense = "capguard_full" if capguard else "none"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "logs").mkdir(parents=True, exist_ok=True)
    fixture_servers = attack.fixture["servers"]
    if "payments" in fixture_servers and not include_payments:
        include_payments = True
    servers = _start_servers(workdir, include_payments=include_payments)
    proxy_server = None
    capability_token: str | None = None
    try:
        restore_all(servers.values(), {"servers": fixture_servers})
        if defense == "capguard_full":
            from capguard import capability as cap_mod
            from capguard.proxy import make_capguard
            proxy_server = make_capguard(
                bind_addr=("127.0.0.1", _free_port()),
                log_path=str(workdir / "logs" / "agent.jsonl"),
                upstream_urls={name: srv.url for name, srv in servers.items()},
            )
            proxy_server.start()
            _trusted_raw = attack.fixture.get("principals", {}).get("trusted")
            _trusted_set = (
                frozenset(str(x) for x in _trusted_raw if isinstance(x, str) and x)
                if isinstance(_trusted_raw, list)
                else frozenset()
            )
            proxy_server.seed_session(
                invoking_principal=attack.invoking_principal,
                user_prompt=attack.prompt,
                trusted_principals=_trusted_set,
            )
            # Mint a session capability granting the invoking principal the
            # full tool surface for the run. cap_mod.mint is human-authored;
            # if the human hasn't filled it in yet this raises immediately
            # (no silent fallback, hard rule 7).
            permitted = tuple(t.name for t in all_tools(include_payments=include_payments))
            capability_token = cap_mod.mint(
                principal=attack.invoking_principal,
                permitted_tools=permitted,
                purpose=infer_mint_purpose(attack.fixture),
                valid_from=time.time() - 1,
                valid_to=time.time() + 3600,
                secret=proxy_server.config.secret,
            )
            endpoints = {
                name: ServerEndpoint(name=name, url=proxy_server.url_for(name))
                for name in servers
            }
        elif defense == "baseline_combined":
            from capguard.baselines.baseline_combined import (
                make_baseline_combined_proxy,
            )

            proxy_server = make_baseline_combined_proxy(
                bind_addr=("127.0.0.1", _free_port()),
                log_path=str(workdir / "logs" / "agent.jsonl"),
                upstream_urls={name: srv.url for name, srv in servers.items()},
                invoking_principal=attack.invoking_principal,
                approved_tools=load_approved_plan(attack),
            )
            proxy_server.start()
            endpoints = {
                name: ServerEndpoint(name=name, url=proxy_server.url_for(name))
                for name in servers
            }
        else:
            endpoints = {
                name: ServerEndpoint(name=name, url=server.url)
                for name, server in servers.items()
            }
        agent_log = workdir / "logs" / "agent.jsonl"
        config = AgentRunConfig(
            principal=attack.invoking_principal,
            model=model,
            log_path=str(agent_log),
            cache_dir=cache_dir,
            tools=all_tools(include_payments=include_payments),
            capability_token=capability_token,
        )
        result = run_agent(
            prompt=attack.prompt,
            config=config,
            client=client,
            endpoints=endpoints,
        )
    finally:
        if proxy_server is not None:
            proxy_server.stop()
        _stop_servers(servers)

    score = score_run(attack.success, result.tool_calls)
    outcome = RunOutcome(
        run_id=result.run_id,
        attack_success=score["attack_success"],
        iterations=result.iterations,
        exit_reason=result.exit_reason,
        final_text=result.final_text,
        tool_calls=result.tool_calls,
    )
    return outcome


def run_k(
    attack: AttackSpec,
    *,
    make_client_fn,
    model: str,
    k: int,
    base_dir: Path,
    defense: str = "none",
    cache_dir: str | None = None,
) -> list[RunOutcome]:
    base_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    outcomes = []
    for i in range(k):
        run_dir = base_dir / f"run_{i:03d}"
        client = make_client_fn()
        outcome = run_one(
            attack,
            client=client,
            model=model,
            workdir=run_dir,
            defense=defense,
            cache_dir=cache_dir,
        )
        outcomes.append(outcome)
        summary.append({
            "run_id": outcome.run_id,
            "i": i,
            "attack_success": outcome.attack_success,
            "iterations": outcome.iterations,
            "exit_reason": outcome.exit_reason,
        })
    (base_dir / "summary.jsonl").write_text(
        "\n".join(json.dumps(s, sort_keys=True) for s in summary) + "\n"
    )
    return outcomes


# ---------- CLI ----------

def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("attack_path")
    ap.add_argument("--orchestrator", default="minimal", choices=["minimal", "langgraph"])
    ap.add_argument("--model", default=os.environ.get("FRONTIER_MODEL", "claude-sonnet-4-6"))
    ap.add_argument("--provider", default=os.environ.get("PROVIDER", "anthropic"))
    ap.add_argument("--defense", default="none", choices=list(DEFENSE_MODES))
    ap.add_argument("--capguard", default=None, choices=["off", "on"])
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--scripted", help="path to a JSON file of ScriptedSteps for offline tests")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.orchestrator != "minimal":
        raise SystemExit("only --orchestrator minimal is wired for now")

    attack = load_attack(args.attack_path)
    out_root = Path(args.out) if args.out else DEFAULT_RESULTS / "runs" / time.strftime(
        "%Y%m%d-%H%M%S") / Path(args.attack_path).name
    cache_dir = os.environ.get("LLM_CACHE_DIR", str(DEFAULT_RESULTS / "llm_cache"))

    if args.scripted:
        steps_payload = json.loads(Path(args.scripted).read_text())
        steps = [ScriptedStep(**s) for s in steps_payload]

        def factory():
            return ScriptedClient(steps)
    else:
        def factory():
            return make_client(args.provider)

    outcomes = run_k(
        attack,
        make_client_fn=factory,
        model=args.model,
        k=args.k,
        base_dir=out_root,
        defense=(
            ("capguard_full" if args.capguard == "on" else "none")
            if args.capguard is not None
            else args.defense
        ),
        cache_dir=cache_dir,
    )
    n = len(outcomes)
    succ = sum(1 for o in outcomes if o.attack_success)
    print(json.dumps({
        "attack": str(args.attack_path),
        "k": n,
        "successes": succ,
        "asr": succ / n if n else None,
        "results_dir": str(out_root),
    }, indent=2))


if __name__ == "__main__":
    _main()
