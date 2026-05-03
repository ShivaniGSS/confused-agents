"""Mock Gmail-like MCP server.

Exposes three operations:
  * list_messages(folder)         -> [{id, author, subject, ts}, ...]
  * read_message(id)              -> {id, author, recipient, subject, body, ts}
  * send_message(to, subject, body) -> {id}

Every record carries a provenance_label naming the principal who
authored it (CLAUDE.md hard rule 4). The provenance side channel in
each RPC response maps message_id -> author principal. CapGuard's proxy
strips this before forwarding to the orchestrator.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from . import _common as common
from ._common import BaseRPCServer, RPCContext, RPCResponse, TableSpec

SERVER_NAME = "gmail"

TABLES = [
    TableSpec(
        name="messages",
        columns=[
            ("id", "TEXT NOT NULL"),
            ("author", "TEXT NOT NULL"),
            ("recipient", "TEXT NOT NULL"),
            ("subject", "TEXT NOT NULL"),
            ("body", "TEXT NOT NULL"),
            ("folder", "TEXT NOT NULL"),  # "inbox" or "sent"
            ("ts", "REAL NOT NULL"),
        ],
        primary_key="id",
    )
]


def _row_meta(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "author": row["author"],
        "subject": row["subject"],
        "ts": row["ts"],
    }


def _row_full(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "author": row["author"],
        "recipient": row["recipient"],
        "subject": row["subject"],
        "body": row["body"],
        "ts": row["ts"],
    }


def list_messages(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    folder = ctx.params.get("folder", "inbox")
    if folder not in ("inbox", "sent"):
        raise ValueError(f"unsupported folder: {folder!r}")
    if folder == "inbox":
        rows = conn.execute(
            "SELECT id, author, recipient, subject, body, ts, folder, "
            f"{common.PURPOSE_COLUMN} FROM messages "
            "WHERE recipient = ? AND folder = 'inbox' ORDER BY ts ASC",
            (ctx.principal,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, author, recipient, subject, body, ts, folder, "
            f"{common.PURPOSE_COLUMN} FROM messages "
            "WHERE author = ? AND folder = 'sent' ORDER BY ts ASC",
            (ctx.principal,),
        ).fetchall()
    result = [_row_meta(r) for r in rows]
    provenance = {
        r["id"]: {"principal": r["author"], "purpose_when_authored": r[common.PURPOSE_COLUMN]}
        for r in rows
    }
    return RPCResponse(result=result, provenance=provenance)


def read_message(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    msg_id = ctx.params.get("id")
    if not isinstance(msg_id, str) or not msg_id:
        raise ValueError("read_message requires non-empty 'id'")
    row = conn.execute(
        f"SELECT id, author, recipient, subject, body, ts, {common.PURPOSE_COLUMN} "
        "FROM messages WHERE id = ?",
        (msg_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no such message: {msg_id}")
    if row["recipient"] != ctx.principal and row["author"] != ctx.principal:
        raise PermissionError(f"principal {ctx.principal} cannot read message {msg_id}")
    return RPCResponse(
        result=_row_full(row),
        provenance={row["id"]: {"principal": row["author"],
                                "purpose_when_authored": row[common.PURPOSE_COLUMN]}},
    )


def send_message(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    to = ctx.params.get("to")
    subject = ctx.params.get("subject", "")
    body = ctx.params.get("body", "")
    if not isinstance(to, str) or not to:
        raise ValueError("send_message requires non-empty 'to'")
    if not isinstance(subject, str):
        raise ValueError("send_message: 'subject' must be string")
    if not isinstance(body, str):
        raise ValueError("send_message: 'body' must be string")
    new_id = f"msg_{uuid.uuid4().hex[:12]}"
    ts = time.time()
    # Deliver as inbox for recipient.
    conn.execute(
        "INSERT INTO messages (id, author, recipient, subject, body, folder, ts, "
        f"{common.PROVENANCE_COLUMN}) VALUES (?, ?, ?, ?, ?, 'inbox', ?, ?)",
        (new_id, ctx.principal, to, subject, body, ts, ctx.principal),
    )
    # Mirror in sender's sent folder.
    sent_id = f"{new_id}_sent"
    conn.execute(
        "INSERT INTO messages (id, author, recipient, subject, body, folder, ts, "
        f"{common.PROVENANCE_COLUMN}) VALUES (?, ?, ?, ?, ?, 'sent', ?, ?)",
        (sent_id, ctx.principal, to, subject, body, ts, ctx.principal),
    )
    agent_prov = {"principal": ctx.principal, "purpose_when_authored": "top"}
    return RPCResponse(
        result={"id": new_id},
        provenance={new_id: agent_prov, sent_id: agent_prov},
    )


def make_server(
    db_path: str | None = None,
    log_path: str | None = None,
    bind_addr: tuple[str, int] | None = None,
) -> BaseRPCServer:
    server = BaseRPCServer(
        name=SERVER_NAME,
        db_path=db_path or common.env_path("MOCK_GMAIL_DB", "./.state/gmail.sqlite"),
        log_path=log_path or common.env_log("./results", SERVER_NAME),
        bind_addr=bind_addr or common.env_bind("MOCK_GMAIL_ADDR", "127.0.0.1:18081"),
        tables=TABLES,
    )
    server.register("list_messages", list_messages)
    server.register("read_message", read_message)
    server.register("send_message", send_message)
    return server


if __name__ == "__main__":
    common.run_forever(make_server())
