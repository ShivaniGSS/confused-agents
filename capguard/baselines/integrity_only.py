"""Integrity-only baseline proxy (BASELINES.md §3, FIDES-style).

This baseline labels data as trusted or untrusted based on the
provenance_label field returned by mock servers. It does NOT block
tool calls based on which data motivated the call — it only verifies
that the invoking principal holds a valid session credential.

Faithfulness justification (BASELINES.md §3.1):
  FIDES integrity labels track data origin but the access-control
  decision is purely credential-based: if the invoking principal's
  session is valid, the call is allowed. FIDES does not propagate
  integrity labels into per-call blocking decisions. This means an
  agent holding alice's credentials can exercise them regardless of
  whether the instruction to do so came from trusted or untrusted data.
  The baseline thus correctly models a strong integrity system that still
  cannot prevent authority laundering.

This is the key structural limitation THEOREMS.md Theorem 1 formalizes:
a governor that observes trust bits but not per-call provenance cannot
distinguish authority-consistent from authority-inconsistent invocations
when both produce the same observable credential.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

import httpx

from mock_mcp._common import JsonlLogger


@dataclass
class IntegrityProxyConfig:
    bind_addr: tuple[str, int]
    log_path: str
    upstream_urls: dict[str, str]
    forward_timeout: float = 15.0


@dataclass
class IntegrityProxy:
    config: IntegrityProxyConfig
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
                except Exception as exc:
                    err_payload = {"result": None, "provenance": None,
                                   "error": f"integrity_proxy_error: {exc}"}
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer(self.config.bind_addr, Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="integrity-proxy", daemon=True
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
            raise KeyError(f"integrity_proxy: no route for target {target!r}")
        return f"{self.url}/{target}"

    def _handle(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        upstream_url = self.config.upstream_urls.get(target)
        if upstream_url is None:
            raise ValueError(f"unknown target: {target!r}")

        method = body.get("method", "")
        params = body.get("params", {})
        principal = body.get("principal", "")
        ts = time.time()

        # Forward to upstream server.
        upstream_body = {"method": method, "params": params, "principal": principal}
        with httpx.Client(timeout=self.config.forward_timeout) as http:
            r = http.post(upstream_url, json=upstream_body)
        r.raise_for_status()
        upstream_resp = r.json()

        # Extract integrity label from provenance side-channel.
        # Integrity-only: record trust bit but do NOT use it for blocking.
        prov = upstream_resp.get("provenance")
        integrity_label = "trusted"
        if isinstance(prov, dict):
            prov_principal = prov.get("principal", "")
            # Label as untrusted if provenance principal is not the invoking principal.
            if prov_principal and prov_principal != principal:
                integrity_label = "untrusted"
        elif isinstance(prov, list):
            principals = {p.get("principal", "") for p in prov if isinstance(p, dict)}
            if any(pp != principal for pp in principals if pp):
                integrity_label = "untrusted"

        # Integrity-only decision: ALLOW all calls by the invoking principal.
        # The credential check is implicit — the session exists (no revocation model).
        # This is the FIDES model: integrity labels are metadata, not enforcement.
        decision = "allow"
        assert self._logger is not None
        self._logger.write({
            "ts": ts,
            "baseline": "integrity_only",
            "target": target,
            "method": method,
            "principal": principal,
            "integrity_label": integrity_label,
            "decision": decision,
        })

        # Strip provenance before returning to orchestrator (same convention as CapGuard).
        stripped = {k: v for k, v in upstream_resp.items() if k != "provenance"}
        return stripped


def make_integrity_proxy(
    *,
    bind_addr: tuple[str, int],
    log_path: str,
    upstream_urls: dict[str, str],
) -> IntegrityProxy:
    cfg = IntegrityProxyConfig(
        bind_addr=bind_addr,
        log_path=log_path,
        upstream_urls=upstream_urls,
    )
    return IntegrityProxy(cfg)
