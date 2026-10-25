"""Append-only JSONL event log. Agents never see it; metrics are computed from it after the fact."""
from __future__ import annotations

import json
from pathlib import Path


class NullLog:
    def emit(self, **fields) -> None:
        pass


class EventLog:
    def __init__(self, path: str | Path | None = None, keep: bool = False):
        self.path = Path(path) if path else None
        self.events: list[dict] | None = [] if keep else None
        self._fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")

    def emit(self, **fields) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if self.events is not None:
            self.events.append(fields)
        if self._fh:
            self._fh.write(json.dumps(fields, separators=(",", ":")) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def read_events(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
