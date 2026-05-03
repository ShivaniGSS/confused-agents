"""Combined baseline: integrity + plan + recipient checks.

This baseline intentionally models a strong labeled-data defense that still
does not enforce capability-bound subject equality.
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

CONSEQUENTIAL_TOOLS = {
    "gmail.send_message",
    "drive.share_with",
    "drive.delete_file",
    "drive.restore_file",
    "calendar.create_event",
    "payments.commit_payment",
}

_MIN_SUBSTRING_LEN = 8


@dataclass
class CombinedProxyConfig:
    bind_addr: tuple[str, int]
    log_path: str
    upstream_urls: dict[str, str]
    invoking_principal: str
    approved_tools: frozenset[str]
    forward_timeout: float = 15.0


class CombinedBlock(Exception):
    pass


@dataclass
class BaselineCombinedProxy:
    config: CombinedProxyConfig
    _httpd: Optional[ThreadingHTTPServer] = field(default=None, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _logger: Optional[JsonlLogger] = field(default=None, init=False)
    # (fragment, principals, authorized_readers)
    _fragments: list[tuple[str, frozenset[str], frozenset[str]]] = field(
        default_factory=list, init=False
    )

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
                except CombinedBlock as blk:
                    err_payload = {
                        "result": None,
                        "provenance": None,
                        "error": f"baseline_combined_block: {blk}",
                    }
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as exc:
                    err_payload = {
                        "result": None,
                        "provenance": None,
                        "error": f"baseline_combined_error: {exc}",
                    }
                    payload = json.dumps(err_payload).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer(self.config.bind_addr, Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="baseline-combined-proxy", daemon=True
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
            raise KeyError(f"baseline_combined: no route for target {target!r}")
        return f"{self.url}/{target}"

    def _handle(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        upstream_url = self.config.upstream_urls.get(target)
        if upstream_url is None:
            raise CombinedBlock(f"unknown target: {target!r}")
        method = body.get("method", "")
        params = body.get("params", {})
        principal = body.get("principal", "")
        if principal != self.config.invoking_principal:
            raise CombinedBlock("invoking_principal_mismatch")
        canonical_tool = method if "." in method else f"{target}.{method}"

        # Check 1: capability-tagging plan.
        if self.config.approved_tools and canonical_tool not in self.config.approved_tools:
            self._log(principal, canonical_tool, "block", "not_in_plan")
            raise CombinedBlock(f"not_in_plan:{canonical_tool}")

        matched = self._matched_fragments(params)

        # Check 2: integrity on consequential tools.
        if canonical_tool in CONSEQUENTIAL_TOOLS:
            principals = set()
            for _txt, ps, _readers in matched:
                principals |= set(ps)
            foreign = {p for p in principals if p != self.config.invoking_principal}
            if foreign:
                self._log(principal, canonical_tool, "block", "integrity_violation")
                raise CombinedBlock(f"integrity_violation:{sorted(foreign)}")

        # Check 3: recipient readers for sharing tools.
        if canonical_tool in {"gmail.send_message", "drive.share_with"}:
            recipient = (
                params.get("to")
                if canonical_tool == "gmail.send_message"
                else params.get("principal")
            )
            if isinstance(recipient, str) and recipient:
                if not self._recipient_authorized(recipient, matched):
                    self._log(principal, canonical_tool, "block", "unauthorized_recipient")
                    raise CombinedBlock(f"unauthorized_recipient:{recipient}")

        # Forward and ingest provenance.
        upstream_body = {"method": method, "params": params, "principal": principal}
        r = httpx.post(upstream_url, json=upstream_body, timeout=self.config.forward_timeout)
        if r.status_code != 200:
            return {"result": None, "provenance": None, "error": r.json().get("error")}
        upstream_resp = r.json()
        self._record_from_response(upstream_resp)
        self._log(principal, canonical_tool, "allow", "passed")
        return {k: v for k, v in upstream_resp.items() if k != "provenance"}

    def _record_from_response(self, upstream_resp: dict[str, Any]) -> None:
        prov_map = upstream_resp.get("provenance") or {}
        if not isinstance(prov_map, dict) or not prov_map:
            return
        principals: set[str] = set()
        readers: set[str] = set()
        for _datum_id, label in prov_map.items():
            if isinstance(label, str):
                principals.add(label)
                readers.add(label)
            elif isinstance(label, dict):
                p = label.get("principal")
                ps = label.get("principals")
                if isinstance(p, str):
                    principals.add(p)
                    readers.add(p)
                elif isinstance(ps, (list, tuple, set)):
                    vals = {str(x) for x in ps}
                    principals.update(vals)
                    readers.update(vals)
                ar = label.get("authorized_readers")
                if isinstance(ar, (list, tuple, set)):
                    readers.update(str(x) for x in ar)
            elif isinstance(label, (list, tuple, set)):
                vals = {str(x) for x in label}
                principals.update(vals)
                readers.update(vals)
        blob = json.dumps(upstream_resp.get("result"), sort_keys=True, separators=(",", ":"), default=str)
        self._fragments.append((blob, frozenset(principals), frozenset(readers)))

    def _matched_fragments(
        self, args: dict
    ) -> list[tuple[str, frozenset[str], frozenset[str]]]:
        blob = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
        out: list[tuple[str, frozenset[str], frozenset[str]]] = []
        for frag in self._fragments:
            if self._overlaps(frag[0], blob):
                out.append(frag)
        return out

    @staticmethod
    def _overlaps(frag: str, text: str) -> bool:
        if not frag or not text:
            return False
        if len(frag) < _MIN_SUBSTRING_LEN:
            return frag in text
        return frag in text or (len(text) >= _MIN_SUBSTRING_LEN and text in frag)

    def _recipient_authorized(
        self,
        recipient: str,
        matched: list[tuple[str, frozenset[str], frozenset[str]]],
    ) -> bool:
        if not matched:
            return True
        for _txt, _ps, readers in matched:
            if not readers:
                continue
            if recipient in readers:
                return True
        return False

    def _log(self, principal: str, tool: str, decision: str, reason: str) -> None:
        assert self._logger is not None
        self._logger.write(
            {
                "kind": "baseline_combined_decision",
                "ts": time.time(),
                "principal": principal,
                "tool": tool,
                "decision": decision,
                "reason": reason,
            }
        )


def make_baseline_combined_proxy(
    *,
    bind_addr: tuple[str, int],
    log_path: str,
    upstream_urls: dict[str, str],
    invoking_principal: str,
    approved_tools: frozenset[str],
) -> BaselineCombinedProxy:
    return BaselineCombinedProxy(
        CombinedProxyConfig(
            bind_addr=bind_addr,
            log_path=log_path,
            upstream_urls=upstream_urls,
            invoking_principal=invoking_principal,
            approved_tools=approved_tools,
        )
    )
