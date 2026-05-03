"""Unified tool surface across the four mock MCP servers.

The orchestrator presents a single flat set of tools to the LLM
(`gmail.list_messages`, `calendar.read_event`, etc.). Each ToolDef
records the (server, method) pair so the orchestrator (or CapGuard
proxy) can route a call to the right RPC URL.

Per CLAUDE.md hard rule 8, this module only declares the wire surface.
The capability/policy/provenance logic lives in capguard/* and is
human-authored.
"""

from __future__ import annotations

from typing import Iterable

from ._llm import ToolDef


def gmail_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="gmail.list_messages",
            description="List messages in a folder of the invoking principal's mailbox.",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "enum": ["inbox", "sent"], "default": "inbox"}
                },
                "required": [],
            },
            server="gmail",
            method="list_messages",
        ),
        ToolDef(
            name="gmail.read_message",
            description="Read the full body of a single message by id.",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            server="gmail",
            method="read_message",
        ),
        ToolDef(
            name="gmail.send_message",
            description=(
                "Send an email from the invoking principal. IRREVERSIBLE: a sent "
                "message cannot be unsent. The recipient address must be a single "
                "principal id."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
            server="gmail",
            method="send_message",
        ),
    ]


def calendar_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="calendar.list_events",
            description="List calendar events for the invoking principal in a date range.",
            input_schema={
                "type": "object",
                "properties": {
                    "date_range": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "ISO 8601 timestamp"},
                            "end": {"type": "string", "description": "ISO 8601 timestamp"},
                        },
                        "required": ["start", "end"],
                    }
                },
                "required": ["date_range"],
            },
            server="calendar",
            method="list_events",
        ),
        ToolDef(
            name="calendar.read_event",
            description="Read a single calendar event by id, including its description.",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            server="calendar",
            method="read_event",
        ),
        ToolDef(
            name="calendar.create_event",
            description="Create a new calendar event authored by the invoking principal.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                },
                "required": ["title", "start", "end", "attendees", "description"],
            },
            server="calendar",
            method="create_event",
        ),
    ]


def drive_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="drive.list_files",
            description="List files in a drive folder ('shared' | 'private' | 'trash').",
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "enum": ["shared", "private", "trash"], "default": "shared"}
                },
                "required": [],
            },
            server="drive",
            method="list_files",
        ),
        ToolDef(
            name="drive.read_file",
            description="Read the full contents of a drive file by id.",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            server="drive",
            method="read_file",
        ),
        ToolDef(
            name="drive.list_comments",
            description="List comments on a drive file. Comments may have authors distinct from the file author.",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            server="drive",
            method="list_comments",
        ),
        ToolDef(
            name="drive.share_with",
            description="Share a drive file with another principal. REVERSIBLE.",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "principal": {"type": "string"},
                },
                "required": ["id", "principal"],
            },
            server="drive",
            method="share_with",
        ),
        ToolDef(
            name="drive.delete_file",
            description=(
                "Move a drive file to trash. BOUNDED IRREVERSIBILITY: the file "
                "can be restored from trash within a window using restore_file."
            ),
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            server="drive",
            method="delete_file",
        ),
    ]


def payment_tools() -> list[ToolDef]:
    """Payment tools (commit-race case study only).

    Per CLAUDE.md Section 8, payments are NOT in the main 18-attack corpus.
    Pass `include_payments=True` to `all_tools` only for the commit-race
    case study harness.
    """
    return [
        ToolDef(
            name="payments.commit_payment",
            description=(
                "Commit a payment from the invoking principal to a recipient. "
                "IRREVERSIBLE: returns immediately and cannot be rolled back."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "amount": {"type": "number"},
                    "memo": {"type": "string"},
                },
                "required": ["recipient", "amount", "memo"],
            },
            server="payments",
            method="commit_payment",
        ),
        ToolDef(
            name="payments.list_payments",
            description="List payments visible to the invoking principal.",
            input_schema={"type": "object", "properties": {}, "required": []},
            server="payments",
            method="list_payments",
        ),
    ]


def all_tools(include_payments: bool = False) -> list[ToolDef]:
    base = gmail_tools() + calendar_tools() + drive_tools()
    if include_payments:
        base = base + payment_tools()
    return base


def by_name(tools: Iterable[ToolDef]) -> dict[str, ToolDef]:
    return {t.name: t for t in tools}
