from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    id: str
    capability_purpose: str
    history: list[dict[str, Any]] = field(default_factory=list)
    state_changes: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    def __init__(self):
        self.persistent_state: dict[str, Any] = {}

    def start_session(self, session_id: str, capability_purpose: str) -> Session:
        return Session(id=session_id, capability_purpose=capability_purpose)

    def end_session(self, session: Session) -> None:
        self.persistent_state.update(session.state_changes)
