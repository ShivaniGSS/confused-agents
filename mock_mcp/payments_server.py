"""Mock Payments MCP server (commit-race case study only).

Operations:
  * commit_payment(recipient, amount, memo) -> {id, status: "committed"}  IRREVERSIBLE
  * list_payments()                          -> [{id, sender, recipient, amount, memo, ts}, ...]

`commit_payment` is irreversible by design (CLAUDE.md Section 5):
once it returns, the payment is final. No `cancel_payment` or
`refund_payment` operations are exposed. This is the operation
CapGuard's irreversibility-aware pre-invocation check (capguard/
irreversibility.py) is meant to gate.

Per CLAUDE.md Section 8: payments are NOT part of the main 18-attack
corpus; they appear only in the commit-race case study.
"""

from __future__ import annotations

import sqlite3
import time
import uuid

from . import _common as common
from ._common import BaseRPCServer, RPCContext, RPCResponse, TableSpec

SERVER_NAME = "payments"

TABLES = [
    TableSpec(
        name="payments",
        columns=[
            ("id", "TEXT NOT NULL"),
            ("sender", "TEXT NOT NULL"),
            ("recipient", "TEXT NOT NULL"),
            ("amount", "REAL NOT NULL"),
            ("memo", "TEXT NOT NULL"),
            ("ts", "REAL NOT NULL"),
            ("status", "TEXT NOT NULL"),
        ],
        primary_key="id",
    )
]


def commit_payment(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    p = ctx.params
    recipient = p.get("recipient")
    amount = p.get("amount")
    memo = p.get("memo", "")
    if not isinstance(recipient, str) or not recipient:
        raise ValueError("commit_payment requires non-empty 'recipient'")
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError("commit_payment requires positive numeric 'amount'")
    if not isinstance(memo, str):
        raise ValueError("commit_payment 'memo' must be string")
    new_id = f"pay_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO payments (id, sender, recipient, amount, memo, ts, status, "
        f"{common.PROVENANCE_COLUMN}) VALUES (?, ?, ?, ?, ?, ?, 'committed', ?)",
        (new_id, ctx.principal, recipient, float(amount), memo, time.time(), ctx.principal),
    )
    agent_prov = {"principal": ctx.principal, "purpose_when_authored": "top"}
    return RPCResponse(
        result={"id": new_id, "status": "committed"},
        provenance={new_id: agent_prov},
    )


def list_payments(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    rows = conn.execute(
        f"SELECT id, sender, recipient, amount, memo, ts, status, {common.PURPOSE_COLUMN} "
        "FROM payments WHERE sender = ? OR recipient = ? ORDER BY ts ASC",
        (ctx.principal, ctx.principal),
    ).fetchall()
    out = [
        {"id": r["id"], "sender": r["sender"], "recipient": r["recipient"],
         "amount": r["amount"], "memo": r["memo"], "ts": r["ts"], "status": r["status"]}
        for r in rows
    ]
    prov = {
        r["id"]: {"principal": r["sender"],
                  "purpose_when_authored": r[common.PURPOSE_COLUMN]}
        for r in rows
    }
    return RPCResponse(result=out, provenance=prov)


def make_server(
    db_path: str | None = None,
    log_path: str | None = None,
    bind_addr: tuple[str, int] | None = None,
) -> BaseRPCServer:
    server = BaseRPCServer(
        name=SERVER_NAME,
        db_path=db_path or common.env_path("MOCK_PAYMENTS_DB", "./.state/payments.sqlite"),
        log_path=log_path or common.env_log("./results", SERVER_NAME),
        bind_addr=bind_addr or common.env_bind("MOCK_PAYMENTS_ADDR", "127.0.0.1:18084"),
        tables=TABLES,
    )
    server.register("commit_payment", commit_payment)
    server.register("list_payments", list_payments)
    return server


if __name__ == "__main__":
    common.run_forever(make_server())
