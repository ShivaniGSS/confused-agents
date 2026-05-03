"""Capability tokens — signed session credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

from . import purpose_lattice as pl


@dataclass(frozen=True)
class Capability:
    principal: str
    permitted_tools: tuple[str, ...]
    purpose: str
    valid_from: float
    valid_to: float


def _canonical_payload(
    principal: str,
    permitted_tools: tuple[str, ...],
    purpose: str,
    valid_from: float,
    valid_to: float,
) -> bytes:
    obj = {
        "principal": principal,
        "permitted_tools": list(permitted_tools),
        "purpose": purpose,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def mint(
    principal: str,
    permitted_tools: tuple[str, ...],
    purpose: str,
    valid_from: float,
    valid_to: float,
    secret: bytes,
) -> str:
    """Mint ``base64url(payload) || '.' || base64url(hmac-sha256(payload))``."""
    if valid_to <= valid_from:
        raise ValueError("valid_to must be greater than valid_from")
    if not secret:
        raise ValueError("refusing to mint with empty secret")
    payload = _canonical_payload(principal, sorted(permitted_tools), purpose, valid_from, valid_to)
    sig = hmac.new(secret, payload, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    )


def verify(token: str, secret: bytes, *, now_ts: float) -> Capability:
    """Verify HMAC and validity window; return ``Capability`` with normalized purpose."""
    if not token or "." not in token:
        raise ValueError("malformed capability token")
    payload_b64, sig_b64 = token.split(".", 1)
    pad = "=" * ((4 - len(payload_b64) % 4) % 4)
    payload = base64.urlsafe_b64decode(payload_b64 + pad)
    sig = base64.urlsafe_b64decode(sig_b64 + "=" * ((4 - len(sig_b64) % 4) % 4))
    expect = hmac.new(secret, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        raise ValueError("capability signature mismatch")
    data = json.loads(payload.decode("utf-8"))
    principal = data["principal"]
    tools = tuple(data["permitted_tools"])
    purpose_raw = data["purpose"]
    valid_from = float(data["valid_from"])
    valid_to = float(data["valid_to"])
    if now_ts < valid_from or now_ts > valid_to:
        raise ValueError("capability outside validity window")
    purpose = pl.normalize(purpose_raw)
    return Capability(
        principal=principal,
        permitted_tools=tools,
        purpose=purpose,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def can_delegate(parent: Capability, child: Capability) -> bool:
    """Delegation is out of scope for this artifact; always false."""
    return False
