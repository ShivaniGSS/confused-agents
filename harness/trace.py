from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceEntry:
    run_id: str
    turn: int
    timestamp_ms: int
    axis: str
    scenario_id: str
    agent_reasoning: str
    tool_call: dict[str, Any]
    tool_response: dict[str, Any] | None
    context_state: dict[str, Any]
    provenance_attribution: dict[str, Any]
    defense_decisions: dict[str, dict[str, Any]]
    persistent_state_changes: list[dict[str, Any]] = field(default_factory=list)


class TraceWriter:
    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[TraceEntry] = []

    def record(self, entry: TraceEntry) -> None:
        self.entries.append(entry)
        with self.output_path.open("a") as f:
            f.write(json.dumps(asdict(entry), sort_keys=True) + "\n")

    def now_ms(self) -> int:
        return int(time.time() * 1000)
