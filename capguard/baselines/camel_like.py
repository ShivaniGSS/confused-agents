"""CaMeL-like baseline proxy (BASELINES.md §4).

This baseline models a deterministic planner that pre-approves tool
calls at the (server, method) level from a per-fixture plan template.
Tool calls matching a pre-approved (server, method) pair are allowed
regardless of their arguments. Calls to methods not in the plan are
blocked.

Faithfulness justification (BASELINES.md §4.1):
  CaMeL uses a dual-LLM architecture where a privileged planner LLM
  pre-approves actions before an unprivileged worker executes them.
  The planner approves at the capability/action type level, not at the
  argument level — it cannot enumerate all valid argument values at
  plan-authoring time. This means an adversarial injection that causes
  the worker to call an approved method (e.g., gmail.send_message) with
  adversarial arguments (e.g., to=mallory) passes the planner's check.

  Our CaMeL-like baseline faithfully models this by:
  1. Pre-approving (server, method) pairs from a plan template.
  2. Allowing all calls to approved (server, method) pairs, regardless
     of argument values.
  3. Blocking calls to unapproved (server, method) pairs.

  Since fixtures are designed so the attack uses an action type the
  prompt legitimately requires (e.g., send_message for email tasks),
  the plan template necessarily pre-approves it, and the attack succeeds.
  This is the structural limitation BASELINES.md §4.2 documents.

Plan template format (capguard/baselines/plan_templates/<fixture_id>.json):
  {
    "approved_calls": [
      {"server": "gmail", "method": "send_message"},
      {"server": "drive", "method": "share_with"},
      ...
    ]
  }

If no template exists for a fixture, all tool calls are pre-approved
(equivalent to no defense for that fixture). This is the correct
fallback: an absent plan means the planner wasn't given enough
information to restrict anything.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

import httpx

from mock_mcp._common import JsonlLogger


PLAN_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "capguard" / "baselines" / "plan_templates"


@dataclass
class CamelProxyConfig:
    bind_addr: tuple[str, int]
    log_path: str
    upstream_urls: dict[str, str]
    approved_calls: frozenset[tuple[str, str]]  # (server, method) pairs
    forward_timeout: float = 15.0


class CamelBlock(Exception):
    pass


@dataclass
class CamelProxy:
    config: CamelProxyConfig
    _httpd: Optional[ThreadingHTTPServer] = field(default=None, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _logger: Optional[JsonlLogger] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._logger = JsonlLogger(self.config.log_path)

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
                except CamelBlock as blk:
                    err_payload = {"result": None, "provenance": None,
                                   "error": f"camel_block: {blk}"}
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as exc:
                    err_payload = {"result": None, "provenance": None,
                                   "error": f"camel_proxy_error: {exc}"}
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer(self.config.bind_addr, Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="camel-proxy", daemon=True
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
        if target not in self.config.upstream_urls:
            raise KeyError(f"camel_proxy: no route for target {target!r}")
        return f"{self.url}/{target}"

    def _handle(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        upstream_url = self.config.upstream_urls.get(target)
        if upstream_url is None:
            raise ValueError(f"unknown target: {target!r}")

        method = body.get("method", "")
        params = body.get("params", {})
        principal = body.get("principal", "")
        ts = time.time()

        key = (target, method)
        approved = (not self.config.approved_calls) or (key in self.config.approved_calls)

        assert self._logger is not None
        if not approved:
            self._logger.write({
                "ts": ts,
                "baseline": "camel_like",
                "target": target,
                "method": method,
                "principal": principal,
                "decision": "block",
                "reason": f"not_in_plan:{target}.{method}",
            })
            raise CamelBlock(f"{target}.{method} not in pre-approved plan")

        # Approved: forward to upstream, strip provenance, log allow.
        upstream_body = {"method": method, "params": params, "principal": principal}
        with httpx.Client(timeout=self.config.forward_timeout) as http:
            r = http.post(upstream_url, json=upstream_body)
        r.raise_for_status()
        upstream_resp = r.json()

        self._logger.write({
            "ts": ts,
            "baseline": "camel_like",
            "target": target,
            "method": method,
            "principal": principal,
            "decision": "allow",
            "reason": "in_plan",
        })

        stripped = {k: v for k, v in upstream_resp.items() if k != "provenance"}
        return stripped


def _load_approved_calls(fixture_id: str) -> frozenset[tuple[str, str]]:
    """Load plan template for fixture_id; if absent, return empty set (allow-all)."""
    template_path = PLAN_TEMPLATES_DIR / f"{fixture_id}.json"
    if not template_path.exists():
        return frozenset()
    template = json.loads(template_path.read_text())
    approved = template.get("approved_calls", [])
    return frozenset((entry["server"], entry["method"]) for entry in approved)


def make_camel_proxy(
    *,
    bind_addr: tuple[str, int],
    log_path: str,
    upstream_urls: dict[str, str],
    fixture_id: str = "",
) -> CamelProxy:
    approved = _load_approved_calls(fixture_id) if fixture_id else frozenset()
    cfg = CamelProxyConfig(
        bind_addr=bind_addr,
        log_path=log_path,
        upstream_urls=upstream_urls,
        approved_calls=approved,
    )
    return CamelProxy(cfg)
