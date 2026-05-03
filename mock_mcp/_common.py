"""Shared infrastructure for the mock MCP servers.

Provides:
  * SQLite connection management (one DB per server, file path env-configurable).
  * Schema initialization with a uniform `provenance_label` column on every record.
  * Snapshot / restore via JSON dump / load (used by harness/snapshot.py).
  * A minimal JSON-over-HTTP RPC server (BaseRPCServer) with a method registry,
    a per-call JSONL audit log, and a provenance side-channel in responses.
  * A tiny RPC client (`call`) used by tests, the orchestrator, and CapGuard.

Per CLAUDE.md Section 5:
  - Every record carries a provenance_label naming the principal who authored it.
  - Every RPC response includes provenance labels in a side channel CapGuard reads
    and the orchestrator must not see directly. The convention enforced here is
    that responses have shape {"result": <data>, "provenance": <map-or-list>,
    "error": <str|null>}. CapGuard's proxy is responsible for stripping
    "provenance" before forwarding to the orchestrator.
  - Every operation is logged to JSONL with timestamp, principal, method, params.

Per CLAUDE.md Section 1, hard rule 7: no silent fallbacks. Malformed input,
missing principal, unknown method, schema mismatch -> raise.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import sqlite3
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


# ---------- SQLite helpers ----------

PROVENANCE_COLUMN = "provenance_label"
PURPOSE_COLUMN = "purpose_when_authored"


def _ensure_parent(path: str) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)


def open_db(path: str) -> sqlite3.Connection:
    """Open a SQLite DB at `path`, creating parent dirs as needed.

    Connections use ROW factory and have foreign keys + WAL enabled.
    """
    _ensure_parent(path)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@dataclass
class TableSpec:
    """Schema spec for a single table in a mock-server DB.

    Every table created via init_schema() automatically gets a
    provenance_label TEXT NOT NULL column. That is non-negotiable
    (CLAUDE.md hard rule 4).
    """

    name: str
    columns: list[tuple[str, str]]  # (column_name, sqlite_type_with_constraints)
    primary_key: str = "id"

    def create_sql(self) -> str:
        cols = list(self.columns)
        if not any(c[0] == PROVENANCE_COLUMN for c in cols):
            cols.append((PROVENANCE_COLUMN, "TEXT NOT NULL"))
        if not any(c[0] == PURPOSE_COLUMN for c in cols):
            cols.append((PURPOSE_COLUMN, "TEXT NOT NULL DEFAULT 'top'"))
        col_sql = ",\n  ".join(f"{name} {typ}" for name, typ in cols)
        return (
            f"CREATE TABLE IF NOT EXISTS {self.name} (\n  {col_sql},\n"
            f"  PRIMARY KEY ({self.primary_key})\n)"
        )


def init_schema(conn: sqlite3.Connection, tables: Iterable[TableSpec]) -> None:
    for t in tables:
        conn.execute(t.create_sql())
        _migrate_required_columns(conn, t.name)


def _migrate_required_columns(conn: sqlite3.Connection, table_name: str) -> None:
    """Backfill required metadata columns on pre-existing tables.

    Older local DBs may predate PURPOSE_COLUMN. CREATE TABLE IF NOT EXISTS
    will not alter those tables, so we add missing columns explicitly.
    """
    cols = {
        r["name"]
        for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if PROVENANCE_COLUMN not in cols:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN "
            f"{PROVENANCE_COLUMN} TEXT NOT NULL DEFAULT 'system@bootstrap'"
        )
    if PURPOSE_COLUMN not in cols:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN "
            f"{PURPOSE_COLUMN} TEXT NOT NULL DEFAULT 'top'"
        )


def _ensure_columns_for_restore(
    conn: sqlite3.Connection, table_name: str, rows: list[dict[str, Any]]
) -> None:
    """Align table schema with fixture rows before INSERT.

    Local SQLite files may predate newer fixture fields (e.g.
    purpose_when_authored). init_schema() migrates known tables, but
    restore must also tolerate schema drift so harness runs do not fail
    mid-corpus.
    """
    if not rows:
        return
    want: set[str] = set()
    for row in rows:
        want.update(row.keys())
    have = {
        r["name"]
        for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for col in sorted(want - have):
        safe = col.replace('"', '""')
        conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe}" TEXT')


# ---------- Snapshot / restore ----------

def snapshot_db(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Dump every user table to a {table_name: [row_dict, ...]} mapping."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = [r["name"] for r in cur.fetchall()]
    out: dict[str, list[dict[str, Any]]] = {}
    for t in tables:
        rows = conn.execute(f"SELECT * FROM {t}").fetchall()
        out[t] = [dict(r) for r in rows]
    return out


def restore_db(conn: sqlite3.Connection, snapshot: dict[str, list[dict[str, Any]]]) -> None:
    """Replace contents of all named tables with the snapshot rows.

    Tables not present in `snapshot` are wiped. Tables present in
    `snapshot` but missing from the DB raise (no silent fallback).
    """
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    db_tables = {r["name"] for r in cur.fetchall()}
    snap_tables = set(snapshot.keys())
    unknown = snap_tables - db_tables
    if unknown:
        raise ValueError(f"snapshot references unknown tables: {sorted(unknown)}")
    conn.execute("BEGIN")
    try:
        for t in db_tables:
            conn.execute(f"DELETE FROM {t}")
        for t, rows in snapshot.items():
            _ensure_columns_for_restore(conn, t, rows)
        for t, rows in snapshot.items():
            for row in rows:
                _validate_provenance(t, row)
                cols = list(row.keys())
                placeholders = ",".join("?" for _ in cols)
                col_sql = ",".join(cols)
                values = [_encode_value(row[c]) for c in cols]
                conn.execute(
                    f"INSERT INTO {t} ({col_sql}) VALUES ({placeholders})",
                    values,
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _encode_value(v: Any) -> Any:
    """SQLite parameter binding only accepts scalars. Structured fixture
    values (lists, dicts) are JSON-encoded so they round-trip through
    TEXT columns; the per-server handlers re-decode them on read.
    """
    if isinstance(v, (list, dict)):
        return json.dumps(v, separators=(",", ":"), sort_keys=True)
    return v


def _validate_provenance(table: str, row: dict[str, Any]) -> None:
    label = row.get(PROVENANCE_COLUMN)
    if not isinstance(label, str) or not label.strip():
        raise ValueError(
            f"row in table {table} is missing a provenance_label "
            f"(hard rule 4); row keys = {sorted(row.keys())}"
        )


# ---------- JSONL audit log ----------

class JsonlLogger:
    """Append-only JSONL logger with a thread lock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("ts", time.time())
        line = json.dumps(record, separators=(",", ":"), sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


# ---------- RPC server ----------

@dataclass
class RPCContext:
    """Per-request context passed to handlers."""

    method: str
    params: dict[str, Any]
    principal: str
    request_id: str
    server_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.principal, str) or not self.principal.strip():
            raise ValueError("RPCContext.principal must be a non-empty string")


@dataclass
class RPCResponse:
    """Response envelope. The `provenance` field is the side channel CapGuard
    reads and the orchestrator must not see directly.
    """

    result: Any
    provenance: Any = None
    error: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {"result": self.result, "provenance": self.provenance, "error": self.error}


HandlerFn = Callable[[RPCContext, sqlite3.Connection], RPCResponse]


@dataclass
class BaseRPCServer:
    """Minimal JSON-over-HTTP RPC server.

    Subclasses register methods with `register(name, handler)`. Each request
    is a POST to `/` with body:

        {"method": "<name>", "params": {...}, "principal": "<id>"}

    Response body:

        {"result": ..., "provenance": ..., "error": null}

    or, on error:

        {"result": null, "provenance": null, "error": "<message>"}
    """

    name: str
    db_path: str
    log_path: str
    bind_addr: tuple[str, int]
    tables: list[TableSpec] = field(default_factory=list)
    handlers: dict[str, HandlerFn] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.conn = open_db(self.db_path)
        init_schema(self.conn, self.tables)
        self.logger = JsonlLogger(self.log_path)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._req_counter = 0
        self._counter_lock = threading.Lock()

    # ---- registration ----
    def register(self, method: str, handler: HandlerFn) -> None:
        if method in self.handlers:
            raise ValueError(f"method {method!r} already registered on {self.name}")
        self.handlers[method] = handler

    def method(self, name: Optional[str] = None) -> Callable[[HandlerFn], HandlerFn]:
        def decorator(fn: HandlerFn) -> HandlerFn:
            self.register(name or fn.__name__, fn)
            return fn

        return decorator

    # ---- snapshot / restore (used by harness) ----
    def snapshot(self) -> dict[str, Any]:
        return snapshot_db(self.conn)

    def restore(self, snap: dict[str, Any]) -> None:
        restore_db(self.conn, snap)

    # ---- request dispatch ----
    def _next_id(self) -> str:
        with self._counter_lock:
            self._req_counter += 1
            return f"{self.name}-{self._req_counter}"

    def dispatch(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        method = body.get("method")
        params = body.get("params", {})
        principal = body.get("principal")
        if not isinstance(method, str):
            raise ValueError("request.method must be a string")
        if not isinstance(params, dict):
            raise ValueError("request.params must be an object")
        if not isinstance(principal, str) or not principal.strip():
            raise ValueError("request.principal must be a non-empty string")
        if method not in self.handlers:
            raise KeyError(f"unknown method on {self.name}: {method!r}")
        ctx = RPCContext(
            method=method,
            params=params,
            principal=principal,
            request_id=self._next_id(),
            server_name=self.name,
        )
        self.logger.write({
            "kind": "rpc_request",
            "server": self.name,
            "request_id": ctx.request_id,
            "method": method,
            "principal": principal,
            "params": params,
        })
        try:
            resp = self.handlers[method](ctx, self.conn)
        except Exception as exc:
            self.logger.write({
                "kind": "rpc_error",
                "server": self.name,
                "request_id": ctx.request_id,
                "method": method,
                "principal": principal,
                "error": str(exc),
                "trace": traceback.format_exc(),
            })
            raise
        if not isinstance(resp, RPCResponse):
            raise TypeError(
                f"handler for {method} returned {type(resp).__name__}, not RPCResponse"
            )
        self.logger.write({
            "kind": "rpc_response",
            "server": self.name,
            "request_id": ctx.request_id,
            "method": method,
            "principal": principal,
            "result_summary": _summarize(resp.result),
            "provenance": resp.provenance,
        })
        return resp.to_json()

    # ---- HTTP server lifecycle ----
    def start(self) -> None:
        srv = self  # capture

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # silence stdlib log
                return

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                    resp = srv.dispatch(body)
                    payload = json.dumps(resp).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as exc:
                    err = {"result": None, "provenance": None, "error": str(exc)}
                    payload = json.dumps(err).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer(self.bind_addr, Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name=f"rpc-{self.name}", daemon=True
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

    @contextlib.contextmanager
    def serving(self):
        self.start()
        try:
            yield self
        finally:
            self.stop()

    @property
    def url(self) -> str:
        host, port = self.bind_addr
        return f"http://{host}:{port}/"


def _summarize(value: Any, limit: int = 200) -> Any:
    """Compact summary of a result for the audit log (avoids dumping huge bodies)."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, list):
        return {"_kind": "list", "len": len(value), "head": _summarize(value[0], limit) if value else None}
    if isinstance(value, dict):
        return {"_kind": "dict", "keys": sorted(value.keys())[:16]}
    return {"_kind": type(value).__name__}


# ---------- RPC client (thin) ----------

def call(url: str, method: str, params: dict[str, Any], principal: str,
         timeout: float = 10.0) -> dict[str, Any]:
    """Synchronous JSON-over-HTTP RPC call. Returns the full response envelope
    (with `result`, `provenance`, `error`). Raises on transport error or non-200.
    """
    import httpx  # imported lazily so unit tests of pure helpers don't need it

    payload = {"method": method, "params": params, "principal": principal}
    r = httpx.post(url, json=payload, timeout=timeout)
    if r.status_code != 200:
        try:
            err = r.json().get("error")
        except Exception:
            err = r.text
        raise RuntimeError(f"RPC {method} -> {r.status_code}: {err}")
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"RPC {method} server error: {body['error']}")
    return body


# ---------- env helpers ----------

def env_bind(addr_var: str, default: str) -> tuple[str, int]:
    raw = os.environ.get(addr_var, default)
    host, _, port = raw.partition(":")
    if not host or not port:
        raise ValueError(f"{addr_var} must be HOST:PORT, got {raw!r}")
    return host, int(port)


def env_path(path_var: str, default: str) -> str:
    return os.environ.get(path_var, default)


def env_log(default_dir: str, server_name: str) -> str:
    base = os.environ.get("RESULTS_DIR", default_dir)
    return str(Path(base) / "mock_mcp" / f"{server_name}.jsonl")


# ---------- main-style helper ----------

def run_forever(server: BaseRPCServer) -> None:
    """Serve until SIGINT. Used by the per-server CLI entrypoints."""
    server.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
