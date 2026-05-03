"""Authority-flow labels and conservative substring propagation."""

from __future__ import annotations

import json
from typing import Any

from . import purpose_lattice as pl

# Ignore very short accidental matches; still sound (may miss rare attacks).
_MIN_SUBSTRING_LEN = 8


class ProvenanceTracker:
    """Tracks labelled text fragments from the user prompt and tool results."""

    def __init__(self) -> None:
        self._invoking: str | None = None
        # (fragment, principal labels, purpose label)
        self._fragments: list[tuple[str, frozenset[str], str]] = []

    def seed(self, invoking_principal: str, user_prompt: str) -> None:
        """Call once per run: register P0's instruction at purpose **session**."""
        self._invoking = invoking_principal
        self._fragments = [
            (
                user_prompt,
                frozenset({invoking_principal}),
                "top",
            )
        ]

    def record_returned(
        self,
        datum_id: str,
        value: Any,
        labels: set[str],
        purpose_label: str | None = None,
    ) -> None:
        """Attach L_auth and Purp to a serialized tool result (proxy calls this)."""
        if self._invoking is None:
            raise RuntimeError("ProvenanceTracker.seed() must run before record_returned")
        text = value if isinstance(value, str) else json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        )
        authors = frozenset(labels)
        if purpose_label is not None:
            purp = pl.normalize(purpose_label)
        else:
            purp = pl.purpose_for_tool_response(
                invoking_principal=self._invoking,
                author_principals=authors,
            )
        self._fragments.append((text, authors, purp))

    def labels_for_text(self, text: str) -> set[str]:
        out: set[str] = set()
        for frag, principals, _ in self._fragments:
            if self._frag_overlaps(frag, text):
                out |= set(principals)
        return out

    def labels_for_args(self, args: dict) -> set[str]:
        blob = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
        out = self.labels_for_text(blob)
        # No substring hit means args do not cite any tracked (prompt or tool-returned)
        # fragment. Attribute the call to the invoking principal only — otherwise
        # check_authority sees an empty arg_labels set and blocks every such tool
        # call (spurious 100% FPR on benign workloads).
        if not out and self._invoking is not None:
            return {self._invoking}
        return out

    def purpose_join_for_justify(self, args: dict) -> str:
        blob = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
        purposes: set[str] = set()
        for frag, _principals, purp in self._fragments:
            if self._frag_overlaps(frag, blob):
                purposes.add(purp)
        return pl.join_many(frozenset(purposes))

    @staticmethod
    def _frag_overlaps(frag: str, text: str) -> bool:
        if not frag or not text:
            return False
        if len(frag) < _MIN_SUBSTRING_LEN:
            return frag in text
        if frag in text:
            return True
        if len(text) >= _MIN_SUBSTRING_LEN and text in frag:
            return True
        return False
