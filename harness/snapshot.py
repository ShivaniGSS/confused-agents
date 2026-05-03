"""Snapshot / restore across the multi-server fixture (CLAUDE.md Section 9).

A "fixture snapshot" is the full state of every mock server's SQLite DB,
encoded as a single JSON document of shape:

    {
      "servers": {
        "<server_name>": {<table_name>: [<row>, ...], ...},
        ...
      }
    }

A fixture file (e.g., attacks/fixtures/.../fixture.json) is a snapshot
plus optional metadata under "principals" / "notes". Loading a fixture
into a set of running servers calls server.restore(snapshot[server.name])
on each, which in turn validates that every row carries a
provenance_label (CLAUDE.md hard rule 4).
"""

from __future__ import annotations

import json
import tarfile
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from mock_mcp._common import BaseRPCServer


def snapshot_all(servers: Iterable[BaseRPCServer]) -> dict[str, Any]:
    out = {"servers": {}}
    for s in servers:
        out["servers"][s.name] = s.snapshot()
    return out


def restore_all(servers: Iterable[BaseRPCServer], snap: dict[str, Any]) -> None:
    by_name = {s.name: s for s in servers}
    server_snap = snap.get("servers", {})
    if not isinstance(server_snap, dict):
        raise ValueError("snapshot must have 'servers' as object")
    for name, sub in server_snap.items():
        if name not in by_name:
            raise KeyError(f"snapshot references unknown server: {name!r}")
        by_name[name].restore(sub)


def load_fixture(path: str | Path) -> dict[str, Any]:
    """Load a fixture file. Accepts either a snapshot-shaped JSON document
    (with top-level "servers" key) or the legacy fixture format that nests
    snapshot data under "servers" alongside metadata; in either case we
    return the snapshot-shaped subset.
    """
    p = Path(path)
    raw = json.loads(p.read_text())
    if "servers" not in raw:
        raise ValueError(f"{path}: fixture missing 'servers' key")
    return {"servers": raw["servers"]}


def save_snapshot_tar(snap: dict[str, Any], tar_path: str | Path) -> None:
    """Persist a snapshot as a one-file tarball (manual: 'tarball per fixture')."""
    p = Path(tar_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snap, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with tarfile.open(p, "w:gz") as tf:
        info = tarfile.TarInfo(name="snapshot.json")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))


def load_snapshot_tar(tar_path: str | Path) -> dict[str, Any]:
    p = Path(tar_path)
    with tarfile.open(p, "r:gz") as tf:
        member = tf.getmember("snapshot.json")
        f = tf.extractfile(member)
        if f is None:
            raise IOError(f"could not read snapshot.json from {p}")
        return json.loads(f.read().decode("utf-8"))
