"""CapGuard proxy — HTTP interception layer (Claude-scoped per hard rule 8).

This file is wire-protocol plumbing only. It receives RPC calls from
the orchestrator on a single bind address, looks up the target mock
server by `target` field in the request, calls into:

  * capguard.capability.verify — verify the presented token
  * capguard.provenance.ProvenanceTracker — compute L^auth(args)
  * capguard.policy.check — authority-consistency predicate
  * capguard.irreversibility.stricter_check — pre-invocation tightening

…and either forwards to the underlying mock server or blocks. Every
decision (allow/block) is logged to JSONL with a structured reason.

Wire convention. The orchestrator POSTs JSON to
`http://<capguard-addr>/<target>` with body:

    {
      "method":   "<server.method>" or just "<method>" if path names server,
      "params":   {...},
      "principal": "<id>",          # the invoking principal
      "capability": "<token>"       # signed capability presented
    }

CapGuard responds with the same envelope shape as the underlying mock
server (`result`, `provenance`, `error`) but ALWAYS strips
`provenance` before returning to the orchestrator (the side channel
must not be tamperable; this proxy is its only consumer).

Per CLAUDE.md hard rule 7 (no silent fallbacks): malformed requests,
missing capability tokens, unknown targets, and verification failures
all raise / return error responses with explicit reasons. The proxy
NEVER silently allows a call.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import httpx

from mock_mcp._common import JsonlLogger

from . import capability as cap_mod
from . import irreversibility as irr_mod
from . import policy as pol_mod
from . import provenance as prov_mod
from . import purpose_lattice as pl


@dataclass
class TargetRoute:
    """Mapping from a CapGuard URL path segment to an underlying mock-server URL."""
    name: str
    upstream_url: str


@dataclass
class CapGuardConfig:
    bind_addr: tuple[str, int]
    log_path: str
    routes: dict[str, TargetRoute]
    secret: bytes
    forward_timeout: float = 15.0


@dataclass
class CapGuardServer:
    config: CapGuardConfig
    _httpd: Optional[ThreadingHTTPServer] = field(default=None, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _logger: Optional[JsonlLogger] = field(default=None, init=False)
    # Shared per-session provenance tracker. The orchestrator instantiates
    # one CapGuardServer per agent run, so this is effectively a per-session
    # tracker.
    _tracker: Optional[prov_mod.ProvenanceTracker] = field(default=None, init=False)
    _trusted: frozenset[str] = field(default_factory=frozenset, init=False)

    def __post_init__(self) -> None:
        self._logger = JsonlLogger(self.config.log_path)
        self._tracker = prov_mod.ProvenanceTracker()

    def seed_session(
        self,
        *,
        invoking_principal: str,
        user_prompt: str,
        trusted_principals: frozenset[str] | None = None,
    ) -> None:
        """Register the invoking principal and initial instruction (purpose **session**)."""
        assert self._tracker is not None
        self._tracker.seed(invoking_principal, user_prompt)
        t: set[str] = {invoking_principal}
        if trusted_principals:
            t |= set(trusted_principals)
        self._trusted = frozenset(t)

    # ---- lifecycle ----
    def start(self) -> None:
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b""
                target = self.path.lstrip("/").strip()
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                    resp_payload = srv._handle(target, body)
                    payload = json.dumps(resp_payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except CapGuardBlock as blk:
                    err_payload = {"result": None, "provenance": None,
                                   "error": f"capguard_block: {blk}"}
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as exc:
                    err_payload = {"result": None, "provenance": None,
                                   "error": f"capguard_error: {exc}"}
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer(self.config.bind_addr, Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="capguard-proxy", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def url(self) -> str:
        host, port = self.config.bind_addr
        return f"http://{host}:{port}"

    def url_for(self, target: str) -> str:
        if target not in self.config.routes:
            raise KeyError(f"capguard: no route for target {target!r}")
        return f"{self.url}/{target}"

    # ---- core dispatch ----
    def _handle(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        if target not in self.config.routes:
            raise CapGuardBlock(f"unknown target: {target!r}")
        method = body.get("method")
        params = body.get("params", {})
        principal = body.get("principal")
        token = body.get("capability")
        if not isinstance(method, str) or not method:
            raise CapGuardBlock("missing or invalid 'method'")
        if not isinstance(principal, str) or not principal.strip():
            raise CapGuardBlock("missing 'principal'")
        if not isinstance(token, str) or not token:
            raise CapGuardBlock("missing 'capability' token")

        now = time.time()
        # 1) Verify capability (HUMAN-AUTHORED capability.verify).
        try:
            capability = cap_mod.verify(token, self.config.secret, now_ts=now)
        except Exception as exc:
            self._log_decision(
                decision="block", target=target, method=method, principal=principal,
                reason=f"capability_verification_failed: {exc}",
            )
            raise CapGuardBlock(f"capability_verification_failed: {exc}")

        # Compose the canonical tool id ("server.method") for tag/policy lookup.
        # If `method` already contains a dot, treat it as canonical; otherwise
        # prefix with the target (route name).
        canonical_tool = method if "." in method else f"{target}.{method}"

        if capability.principal != principal:
            self._log_decision(
                decision="block", target=target, method=method, principal=principal,
                reason="capability_principal_mismatch",
                capability_principal=capability.principal,
            )
            raise CapGuardBlock("capability_principal_mismatch")

        # 2) Compute argument labels via ProvenanceTracker.
        arg_labels = self._tracker.labels_for_args(params)
        # Purpose join over justifying data: human-authored. If the tracker
        # exposes purpose_join_for_justify, use it; else policy.check must
        # derive purposes from tracker state or reject (no silent default).
        pj_fn = getattr(self._tracker, "purpose_join_for_justify", None)
        purpose_join = pj_fn(params) if callable(pj_fn) else ""

        # 3) Authority-consistency predicate (HUMAN-AUTHORED).
        decision = pol_mod.check(
            capability=capability, tool=canonical_tool,
            args=params, arg_labels=arg_labels, purpose_join=purpose_join,
            mode=os.environ.get("CAPGUARD_POLICY_MODE", "both"),
        )

        # 4) Irreversibility-aware tightening: only *sensitive* argument
        # fields (body / memo — not recipient routing) carry motivation for
        # commit-race confused-deputy; destination ids alone are not treated
        # as foreign authority taint.
        strict_labels = arg_labels
        try:
            if irr_mod.tag_for(canonical_tool) == "irreversible":
                if canonical_tool == "gmail.send_message":
                    restricted = {k: params[k] for k in ("body", "subject") if k in params}
                elif canonical_tool == "payments.commit_payment":
                    restricted = {k: params[k] for k in ("memo",) if k in params}
                else:
                    restricted = dict(params)
                strict_labels = (
                    self._tracker.labels_for_args(restricted) if restricted else set()
                )
        except KeyError:
            strict_labels = arg_labels

        decision = irr_mod.stricter_check(
            base_decision=decision, invoking_principal=principal,
            tool=canonical_tool, arg_labels=strict_labels,
            trusted=self._trusted,
        )

        if not decision.allowed:
            self._log_decision(
                decision="block", target=target, method=method, principal=principal,
                reason=decision.reason, capability_principal=capability.principal,
                arg_labels=sorted(arg_labels),
            )
            raise CapGuardBlock(decision.reason)

        # 5) Forward to the upstream mock server.
        upstream = self.config.routes[target].upstream_url
        forward_body = {"method": method, "params": params, "principal": principal}
        try:
            r = httpx.post(upstream, json=forward_body, timeout=self.config.forward_timeout)
        except Exception as exc:
            self._log_decision(
                decision="error", target=target, method=method, principal=principal,
                reason=f"forward_failed: {exc}",
            )
            raise
        if r.status_code != 200:
            self._log_decision(
                decision="error", target=target, method=method, principal=principal,
                reason=f"upstream_status_{r.status_code}",
            )
            return {"result": None, "provenance": None, "error": r.json().get("error")}
        upstream_body = r.json()

        # 6) Record returned data with the tracker. Provenance side-channel
        # accepts legacy shapes ({datum_id: principal}) and richer shapes:
        # {datum_id: {"principal": "...", "purpose_when_authored": "..."}}
        # with optional plural keys.
        prov_map = upstream_body.get("provenance") or {}
        if isinstance(prov_map, dict) and prov_map:
            label_set: set[str] = set()
            purpose_labels: set[str] = set()
            for _datum_id, label in prov_map.items():
                if isinstance(label, str):
                    label_set.add(label)
                elif isinstance(label, dict):
                    principal = label.get("principal")
                    principals = label.get("principals")
                    purpose = label.get("purpose_when_authored")
                    if isinstance(principal, str):
                        label_set.add(principal)
                    elif isinstance(principals, (list, tuple, set)):
                        label_set.update(str(x) for x in principals)
                    else:
                        raise ValueError(
                            "capguard: provenance dict must include principal/principals"
                        )
                    if isinstance(purpose, str):
                        purpose_labels.add(purpose)
                elif isinstance(label, (list, tuple, set)):
                    label_set.update(str(x) for x in label)
                else:
                    raise ValueError(
                        f"capguard: unexpected provenance label type {type(label)}"
                    )
            try:
                result_blob = json.dumps(
                    upstream_body.get("result"),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except TypeError as exc:
                raise RuntimeError(
                    f"capguard: cannot JSON-serialize tool result for provenance: {exc}"
                ) from exc
            self._tracker.record_returned(
                datum_id=f"{canonical_tool}@{target}",
                value=result_blob,
                labels=label_set,
                purpose_label=(
                    pl.join_many(frozenset(purpose_labels)) if purpose_labels else None
                ),
            )

        self._log_decision(
            decision="allow", target=target, method=method, principal=principal,
            reason=decision.reason, capability_principal=capability.principal,
            arg_labels=sorted(arg_labels),
        )

        # 7) Strip provenance before returning to the orchestrator. This
        # is the side-channel separation hard rule 5 / Section 5 require.
        return {"result": upstream_body.get("result"), "provenance": None,
                "error": upstream_body.get("error")}


    # ---- log helper ----
    def _log_decision(self, **fields: Any) -> None:
        rec = {"kind": "capguard_decision", "ts": time.time(), **fields}
        assert self._logger is not None
        self._logger.write(rec)


class CapGuardBlock(Exception):
    """Raised internally to propagate a 403-style block decision."""


# ---------- factory used by the harness ----------

def make_capguard(
    *,
    bind_addr: tuple[str, int],
    log_path: str,
    upstream_urls: dict[str, str],
    secret: Optional[bytes] = None,
) -> CapGuardServer:
    """Build a CapGuardServer with one route per upstream mock server.

    `upstream_urls` keys must be one of {"gmail", "calendar", "drive", "payments"}
    (the route names the orchestrator addresses). Values are the underlying
    `BaseRPCServer.url` strings.
    """
    routes = {name: TargetRoute(name=name, upstream_url=url)
              for name, url in upstream_urls.items()}
    return CapGuardServer(
        config=CapGuardConfig(
            bind_addr=bind_addr,
            log_path=log_path,
            routes=routes,
            secret=secret if secret is not None else os.urandom(32),
        )
    )
