"""
storage.py — Minimal append-only event log.

Writes structured events to logs/events.jsonl (one JSON object per line).
Production replacement: Postgres table with INSERT-only role grants, or a
managed ledger service like AWS QLDB. This is a starter implementation
that gives us replay-ability and durability today.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class EventLog:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.log_dir / "events.jsonl"

    def append(self, event_type: str, payload: Dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")

    def read_all(self):
        if not self.events_path.exists():
            return []
        with self.events_path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


# Convenience module-level functions for backward compatibility with the
# original backend/main.py that did `from storage import save_log`.
_default_log = EventLog()


def save_log(payload: Dict[str, Any]) -> None:
    _default_log.append("message_processed", payload)
