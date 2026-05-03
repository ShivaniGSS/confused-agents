"""Day 1 smoke test (CLAUDE.md Section 10, Day 1 end-check).

Verifies that the gmail mock server boots, accepts a fixture restore,
and round-trips provenance through real JSON-over-HTTP RPC calls.

Pass criteria:
  * list_messages returns the inbox messages from the fixture in author/ts order.
  * Provenance side channel maps every returned id to its ground-truth author.
  * read_message returns the full row and a provenance dict containing the
    requested id mapped to its ground-truth author.
  * send_message inserts a row whose provenance equals the calling principal.
"""

from __future__ import annotations

import json
import socket
import tempfile
from pathlib import Path

import pytest

from mock_mcp import _common as common
from mock_mcp import gmail_server


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPO_ROOT / "attacks" / "fixtures" / "scenario_a_calendar" / "attack_01" / "fixture.json"
)
PROVENANCE_PATH = (
    REPO_ROOT / "attacks" / "fixtures" / "scenario_a_calendar" / "attack_01" / "provenance.json"
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def gmail():
    """Spin up a one-shot gmail server on a free port with a temp DB."""
    fixture = json.loads(FIXTURE_PATH.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        port = _free_port()
        server = gmail_server.make_server(
            db_path=str(tmp_path / "gmail.sqlite"),
            log_path=str(tmp_path / "gmail.jsonl"),
            bind_addr=("127.0.0.1", port),
        )
        # Restore the gmail portion of the fixture as a snapshot.
        server.restore(fixture["servers"]["gmail"])
        with server.serving():
            yield server


def test_list_messages_round_trips_provenance(gmail):
    fixture = json.loads(FIXTURE_PATH.read_text())
    ground = json.loads(PROVENANCE_PATH.read_text())["ground_truth"]

    resp = common.call(
        gmail.url, "list_messages",
        params={"folder": "inbox"},
        principal="alice@example.test",
    )

    # Result is a list of message metadata for alice's inbox.
    assert resp["error"] is None
    ids = [m["id"] for m in resp["result"]]
    assert ids == ["msg_a01_001", "msg_a01_002"]

    # Provenance side channel matches ground truth exactly.
    assert resp["provenance"] == {
        "msg_a01_001": ground["msg_a01_001"],
        "msg_a01_002": ground["msg_a01_002"],
    }


def test_read_message_returns_full_body_and_provenance(gmail):
    ground = json.loads(PROVENANCE_PATH.read_text())["ground_truth"]
    resp = common.call(
        gmail.url, "read_message",
        params={"id": "msg_a01_001"},
        principal="alice@example.test",
    )
    assert resp["error"] is None
    msg = resp["result"]
    assert msg["author"] == "bob@example.test"
    assert msg["recipient"] == "alice@example.test"
    assert "latest draft" in msg["body"]
    assert "file_a01_proposal" in msg["body"]
    assert resp["provenance"] == {"msg_a01_001": ground["msg_a01_001"]}


def test_read_message_denies_other_principals(gmail):
    with pytest.raises(RuntimeError, match="cannot read message"):
        common.call(
            gmail.url, "read_message",
            params={"id": "msg_a01_001"},
            principal="mallory@external.test",
        )


def test_send_message_records_caller_as_provenance(gmail):
    resp = common.call(
        gmail.url, "send_message",
        params={"to": "bob@example.test", "subject": "Test", "body": "Hi"},
        principal="alice@example.test",
    )
    assert resp["error"] is None
    new_id = resp["result"]["id"]
    # Both the recipient inbox copy and the sender sent-folder mirror are labelled alice.
    assert resp["provenance"][new_id] == "alice@example.test"

    # Verify the sent message is now visible in alice's sent folder, with the right provenance.
    sent = common.call(
        gmail.url, "list_messages",
        params={"folder": "sent"},
        principal="alice@example.test",
    )
    assert sent["error"] is None
    sent_ids = [m["id"] for m in sent["result"]]
    assert any(sid.startswith(new_id) for sid in sent_ids)
    for sid in sent_ids:
        assert sent["provenance"][sid] == "alice@example.test"


def test_unknown_method_raises(gmail):
    with pytest.raises(RuntimeError, match="unknown method"):
        common.call(
            gmail.url, "nope",
            params={},
            principal="alice@example.test",
        )


def test_missing_principal_raises(gmail):
    import httpx
    # Bypass the typed client so we can send a malformed request.
    r = httpx.post(gmail.url, json={"method": "list_messages", "params": {"folder": "inbox"}})
    assert r.status_code == 500
    assert "principal" in (r.json().get("error") or "")
