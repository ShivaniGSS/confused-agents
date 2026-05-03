"""Mock Calendar MCP server.

Operations:
  * list_events(date_range)            -> [{id, author, title, start, end, attendees}, ...]
  * read_event(id)                     -> {id, author, title, start, end, attendees, description}
  * create_event(title, start, end, attendees, description) -> {id}

Events have an `author` (creator) principal which equals the
`provenance_label` for the event row. Attendees is a JSON-encoded list
of principal ids. The agent's invoking principal sees events where it
is in `attendees`.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import _common as common
from ._common import BaseRPCServer, RPCContext, RPCResponse, TableSpec

SERVER_NAME = "calendar"

TABLES = [
    TableSpec(
        name="events",
        columns=[
            ("id", "TEXT NOT NULL"),
            ("author", "TEXT NOT NULL"),
            ("title", "TEXT NOT NULL"),
            ("start", "TEXT NOT NULL"),  # ISO8601
            ("end", "TEXT NOT NULL"),
            ("attendees", "TEXT NOT NULL"),  # JSON list
            ("description", "TEXT NOT NULL"),
        ],
        primary_key="id",
    )
]


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _attendees(row: sqlite3.Row) -> list[str]:
    return json.loads(row["attendees"])


def _row_meta(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "author": row["author"],
        "title": row["title"],
        "start": row["start"],
        "end": row["end"],
        "attendees": _attendees(row),
    }


def _row_full(row: sqlite3.Row) -> dict[str, Any]:
    out = _row_meta(row)
    out["description"] = row["description"]
    return out


def list_events(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    date_range = ctx.params.get("date_range")
    if not isinstance(date_range, dict):
        raise ValueError("list_events requires 'date_range': {start, end} ISO timestamps")
    start = _parse_iso(date_range["start"])
    end = _parse_iso(date_range["end"])
    rows = conn.execute(
        f"SELECT id, author, title, start, end, attendees, description, "
        f"{common.PURPOSE_COLUMN} FROM events ORDER BY start ASC"
    ).fetchall()
    out_rows = []
    prov: dict[str, Any] = {}
    for r in rows:
        ev_start = _parse_iso(r["start"])
        if not (start <= ev_start <= end):
            continue
        if ctx.principal not in _attendees(r):
            continue
        out_rows.append(_row_meta(r))
        prov[r["id"]] = {"principal": r["author"],
                         "purpose_when_authored": r[common.PURPOSE_COLUMN]}
    return RPCResponse(result=out_rows, provenance=prov)


def read_event(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    ev_id = ctx.params.get("id")
    if not isinstance(ev_id, str) or not ev_id:
        raise ValueError("read_event requires non-empty 'id'")
    row = conn.execute(
        f"SELECT id, author, title, start, end, attendees, description, {common.PURPOSE_COLUMN} "
        "FROM events WHERE id = ?",
        (ev_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no such event: {ev_id}")
    if ctx.principal not in _attendees(row) and ctx.principal != row["author"]:
        raise PermissionError(f"principal {ctx.principal} cannot read event {ev_id}")
    return RPCResponse(
        result=_row_full(row),
        provenance={row["id"]: {"principal": row["author"],
                                "purpose_when_authored": row[common.PURPOSE_COLUMN]}},
    )


def create_event(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    p = ctx.params
    title = p.get("title", "")
    start = p.get("start")
    end = p.get("end")
    attendees = p.get("attendees", [])
    description = p.get("description", "")
    if not isinstance(title, str) or not title:
        raise ValueError("create_event requires non-empty 'title'")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("create_event requires 'start' and 'end' as ISO strings")
    if not isinstance(attendees, list) or not all(isinstance(a, str) for a in attendees):
        raise ValueError("create_event 'attendees' must be a list of principal ids")
    if not isinstance(description, str):
        raise ValueError("create_event 'description' must be string")
    if ctx.principal not in attendees:
        attendees = attendees + [ctx.principal]
    new_id = f"evt_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO events (id, author, title, start, end, attendees, description, "
        f"{common.PROVENANCE_COLUMN}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id, ctx.principal, title, start, end, json.dumps(attendees), description,
         ctx.principal),
    )
    return RPCResponse(
        result={"id": new_id},
        provenance={new_id: {"principal": ctx.principal, "purpose_when_authored": "top"}},
    )


def make_server(
    db_path: str | None = None,
    log_path: str | None = None,
    bind_addr: tuple[str, int] | None = None,
) -> BaseRPCServer:
    server = BaseRPCServer(
        name=SERVER_NAME,
        db_path=db_path or common.env_path("MOCK_CALENDAR_DB", "./.state/calendar.sqlite"),
        log_path=log_path or common.env_log("./results", SERVER_NAME),
        bind_addr=bind_addr or common.env_bind("MOCK_CALENDAR_ADDR", "127.0.0.1:18082"),
        tables=TABLES,
    )
    server.register("list_events", list_events)
    server.register("read_event", read_event)
    server.register("create_event", create_event)
    return server


if __name__ == "__main__":
    common.run_forever(make_server())
