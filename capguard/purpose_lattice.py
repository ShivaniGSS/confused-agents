"""Canonical purpose lattice implementation consumed by CapGuard policy.

Source of truth: PURPOSE_LATTICE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ROOT_CLINICAL = "clinical-care"
ROOT_FINANCIAL = "financial-advisory"
ROOT_OPERATIONS = "operations"
ROOTS = frozenset({ROOT_CLINICAL, ROOT_FINANCIAL, ROOT_OPERATIONS})


@dataclass(frozen=True)
class Purpose:
    root: str
    subject: Optional[str] = None
    sub: Optional[str] = None
    is_top: bool = False


TOP = Purpose(root="", subject=None, sub=None, is_top=True)

_ALIASES: dict[str, Purpose] = {
    "top": TOP,
    "agent_session": TOP,
    "session": TOP,
}


def parse(label: str) -> Purpose:
    raw = label.strip().lower()
    if raw in _ALIASES:
        return _ALIASES[raw]
    parts = raw.split("/")
    root = parts[0]
    if root not in ROOTS:
        raise ValueError(f"unknown purpose root: {root!r}")
    subject: Optional[str] = None
    sub: Optional[str] = None
    for frag in parts[1:]:
        if frag.startswith("patient=") or frag.startswith("client=") or frag.startswith("project="):
            subject = frag.split("=", 1)[1]
        elif frag.startswith("subject="):
            subject = frag.split("=", 1)[1]
        elif frag:
            sub = frag
    return Purpose(root=root, subject=subject, sub=sub, is_top=False)


def serialize(p: Purpose) -> str:
    if p.is_top:
        return "top"
    out = p.root
    if p.subject is not None:
        out += f"/subject={p.subject}"
    if p.sub is not None:
        out += f"/{p.sub}"
    return out


def normalize(label: str) -> str:
    return serialize(parse(label))


def leq(p: Purpose, q: Purpose) -> bool:
    if q.is_top:
        return True
    if p.is_top:
        return False
    if p.root != q.root:
        return False
    if q.subject is not None and q.subject != p.subject:
        return False
    if q.sub is not None and q.sub != p.sub:
        return False
    return True


def least_common_ancestor(p: Purpose, q: Purpose) -> Purpose:
    if p.root == q.root and not p.is_top and not q.is_top:
        return Purpose(root=p.root)
    return TOP


def join(p: Purpose, q: Purpose) -> Purpose:
    if p == q:
        return p
    if p.is_top or q.is_top:
        return TOP
    if leq(p, q):
        return q
    if leq(q, p):
        return p
    return least_common_ancestor(p, q)


def join_many(labels: frozenset[str]) -> str:
    if not labels:
        return serialize(TOP)
    it = iter(labels)
    acc = parse(next(it))
    for nxt in it:
        acc = join(acc, parse(nxt))
    return serialize(acc)


def subject_consistent(
    cap_purp: Purpose,
    invocation_subject: Optional[str | frozenset[str]],
) -> bool:
    if cap_purp.is_top or cap_purp.subject is None:
        return True
    # Operations / project=* binds data provenance (calendar, mail, drive for a
    # project). Tool args like gmail.send_message.to or drive.share_with.principal
    # are routing identifiers — they are not the lattice "subject" for
    # operations; comparing them to the project slug spuriously blocks benign runs.
    if cap_purp.root == ROOT_OPERATIONS:
        return True
    if invocation_subject is None:
        return False
    if isinstance(invocation_subject, frozenset):
        return invocation_subject == frozenset({cap_purp.subject})
    return invocation_subject == cap_purp.subject


def extract_invocation_subject(tool: str, args: dict) -> Optional[str | frozenset[str]]:
    if tool == "gmail.send_message":
        return args.get("to")
    if tool == "drive.share_with":
        return args.get("principal")
    if tool == "payments.commit_payment":
        return args.get("recipient")
    if tool == "calendar.create_event":
        attendees = args.get("attendees")
        if isinstance(attendees, list):
            vals = [str(x).strip().lower() for x in attendees if str(x).strip()]
            if not vals:
                return None
            return frozenset(vals)
        return None
    # Requires ID->author resolution from fixture/runtime state.
    if tool in {"gmail.read_message", "drive.delete_file"}:
        return None
    return None


def purpose_for_tool_response(
    *,
    invoking_principal: str,
    author_principals: frozenset[str],
) -> str:
    # Transitional fallback until fixtures carry explicit purpose_when_authored.
    # Any tool-returned datum defaults to operations, optionally subject-bound.
    if not author_principals:
        return serialize(TOP)
    if author_principals == {invoking_principal}:
        return serialize(Purpose(root=ROOT_OPERATIONS, subject=invoking_principal))
    if len(author_principals) == 1:
        only = next(iter(author_principals))
        return serialize(Purpose(root=ROOT_OPERATIONS, subject=only))
    return serialize(Purpose(root=ROOT_OPERATIONS))
