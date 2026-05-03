"""Mock Drive MCP server.

Operations:
  * list_files(folder)              -> [{id, author, name, folder}, ...]
  * read_file(id)                   -> {id, author, name, content, folder}
  * list_comments(id)               -> [{id, author, text, ts}, ...]
  * share_with(id, principal)       -> {id, shared_with: [...]}
  * delete_file(id)                 -> {id, status: "trashed"}    # bounded delete
  * restore_file(id)                -> {id, status: "restored"}   # for tests of bounded semantics

Two tables:
  * files(id, author, name, content, folder, provenance_label) — folder
    is "shared", "private", or "trash". `delete_file` moves to "trash"
    (bounded irreversibility); `restore_file` restores within the
    bounded window.
  * comments(id, file_id, author, text, ts, provenance_label) — comments
    have their own author distinct from the file author.

Access model: a principal can access a file if author == principal,
the principal appears in `shared_with`, or the file folder is "shared".
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from . import _common as common
from ._common import BaseRPCServer, RPCContext, RPCResponse, TableSpec

SERVER_NAME = "drive"

TABLES = [
    TableSpec(
        name="files",
        columns=[
            ("id", "TEXT NOT NULL"),
            ("author", "TEXT NOT NULL"),
            ("name", "TEXT NOT NULL"),
            ("content", "TEXT NOT NULL"),
            ("folder", "TEXT NOT NULL"),  # "shared" | "private" | "trash"
            ("shared_with", "TEXT NOT NULL DEFAULT '[]'"),  # JSON list of principals
        ],
        primary_key="id",
    ),
    TableSpec(
        name="comments",
        columns=[
            ("id", "TEXT NOT NULL"),
            ("file_id", "TEXT NOT NULL"),
            ("author", "TEXT NOT NULL"),
            ("text", "TEXT NOT NULL"),
            ("ts", "REAL NOT NULL"),
        ],
        primary_key="id",
    ),
]


def _shared_with(row: sqlite3.Row) -> list[str]:
    return json.loads(row["shared_with"]) if row["shared_with"] else []


def _accessible(row: sqlite3.Row, principal: str) -> bool:
    if row["folder"] == "trash":
        return row["author"] == principal
    if row["author"] == principal:
        return True
    if row["folder"] == "shared":
        return True
    return principal in _shared_with(row)


def _file_meta(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "author": row["author"],
        "name": row["name"],
        "folder": row["folder"],
    }


def _file_full(row: sqlite3.Row) -> dict[str, Any]:
    out = _file_meta(row)
    out["content"] = row["content"]
    out["shared_with"] = _shared_with(row)
    return out


def list_files(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    folder = ctx.params.get("folder", "shared")
    if folder not in ("shared", "private", "trash"):
        raise ValueError(f"unknown folder: {folder!r}")
    rows = conn.execute(
        f"SELECT id, author, name, content, folder, shared_with, {common.PURPOSE_COLUMN} "
        "FROM files WHERE folder = ? ORDER BY name ASC",
        (folder,),
    ).fetchall()
    out, prov = [], {}
    for r in rows:
        if not _accessible(r, ctx.principal):
            continue
        out.append(_file_meta(r))
        prov[r["id"]] = {"principal": r["author"],
                         "purpose_when_authored": r[common.PURPOSE_COLUMN]}
    return RPCResponse(result=out, provenance=prov)


def read_file(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    fid = ctx.params.get("id")
    if not isinstance(fid, str) or not fid:
        raise ValueError("read_file requires non-empty 'id'")
    row = conn.execute(
        f"SELECT id, author, name, content, folder, shared_with, {common.PURPOSE_COLUMN} "
        "FROM files WHERE id = ?",
        (fid,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no such file: {fid}")
    if not _accessible(row, ctx.principal):
        raise PermissionError(f"principal {ctx.principal} cannot read file {fid}")
    return RPCResponse(
        result=_file_full(row),
        provenance={row["id"]: {"principal": row["author"],
                                "purpose_when_authored": row[common.PURPOSE_COLUMN]}},
    )


def list_comments(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    fid = ctx.params.get("id")
    if not isinstance(fid, str) or not fid:
        raise ValueError("list_comments requires non-empty 'id'")
    file_row = conn.execute(
        "SELECT id, author, name, content, folder, shared_with FROM files WHERE id = ?",
        (fid,),
    ).fetchone()
    if file_row is None:
        raise KeyError(f"no such file: {fid}")
    if not _accessible(file_row, ctx.principal):
        raise PermissionError(f"principal {ctx.principal} cannot read comments on {fid}")
    rows = conn.execute(
        f"SELECT id, file_id, author, text, ts, {common.PURPOSE_COLUMN} "
        "FROM comments WHERE file_id = ? ORDER BY ts ASC",
        (fid,),
    ).fetchall()
    out = [
        {"id": r["id"], "file_id": r["file_id"], "author": r["author"],
         "text": r["text"], "ts": r["ts"]}
        for r in rows
    ]
    prov = {
        r["id"]: {"principal": r["author"],
                  "purpose_when_authored": r[common.PURPOSE_COLUMN]}
        for r in rows
    }
    return RPCResponse(result=out, provenance=prov)


def share_with(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    fid = ctx.params.get("id")
    target = ctx.params.get("principal")
    if not isinstance(fid, str) or not fid:
        raise ValueError("share_with requires non-empty 'id'")
    if not isinstance(target, str) or not target:
        raise ValueError("share_with requires non-empty 'principal'")
    row = conn.execute(
        f"SELECT id, author, shared_with, folder, {common.PURPOSE_COLUMN} "
        "FROM files WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no such file: {fid}")
    if row["author"] != ctx.principal and ctx.principal not in _shared_with(row):
        raise PermissionError(f"principal {ctx.principal} cannot reshare file {fid}")
    sw = _shared_with(row)
    if target not in sw:
        sw.append(target)
    conn.execute("UPDATE files SET shared_with = ? WHERE id = ?", (json.dumps(sw), fid))
    return RPCResponse(
        result={"id": fid, "shared_with": sw},
        provenance={fid: {"principal": row["author"],
                          "purpose_when_authored": row[common.PURPOSE_COLUMN]}},
    )


def delete_file(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    fid = ctx.params.get("id")
    if not isinstance(fid, str) or not fid:
        raise ValueError("delete_file requires non-empty 'id'")
    row = conn.execute(
        f"SELECT id, author, folder, {common.PURPOSE_COLUMN} FROM files WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no such file: {fid}")
    if row["author"] != ctx.principal:
        raise PermissionError(f"principal {ctx.principal} cannot delete file {fid}")
    conn.execute("UPDATE files SET folder = 'trash' WHERE id = ?", (fid,))
    return RPCResponse(
        result={"id": fid, "status": "trashed"},
        provenance={fid: {"principal": row["author"],
                          "purpose_when_authored": row[common.PURPOSE_COLUMN]}},
    )


def restore_file(ctx: RPCContext, conn: sqlite3.Connection) -> RPCResponse:
    fid = ctx.params.get("id")
    target_folder = ctx.params.get("folder", "private")
    if target_folder not in ("shared", "private"):
        raise ValueError("restore target folder must be 'shared' or 'private'")
    row = conn.execute(
        f"SELECT id, author, folder, {common.PURPOSE_COLUMN} FROM files WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no such file: {fid}")
    if row["author"] != ctx.principal:
        raise PermissionError(f"principal {ctx.principal} cannot restore file {fid}")
    if row["folder"] != "trash":
        raise ValueError(f"file {fid} is not in trash (folder={row['folder']})")
    conn.execute("UPDATE files SET folder = ? WHERE id = ?", (target_folder, fid))
    return RPCResponse(
        result={"id": fid, "status": "restored", "folder": target_folder},
        provenance={fid: {"principal": row["author"],
                          "purpose_when_authored": row[common.PURPOSE_COLUMN]}},
    )


def make_server(
    db_path: str | None = None,
    log_path: str | None = None,
    bind_addr: tuple[str, int] | None = None,
) -> BaseRPCServer:
    server = BaseRPCServer(
        name=SERVER_NAME,
        db_path=db_path or common.env_path("MOCK_DRIVE_DB", "./.state/drive.sqlite"),
        log_path=log_path or common.env_log("./results", SERVER_NAME),
        bind_addr=bind_addr or common.env_bind("MOCK_DRIVE_ADDR", "127.0.0.1:18083"),
        tables=TABLES,
    )
    server.register("list_files", list_files)
    server.register("read_file", read_file)
    server.register("list_comments", list_comments)
    server.register("share_with", share_with)
    server.register("delete_file", delete_file)
    server.register("restore_file", restore_file)
    return server


if __name__ == "__main__":
    common.run_forever(make_server())
