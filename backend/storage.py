"""
storage.py — Event log with SQLite primary, JSONL mirror.

SQLite (logs/events.db) is the durable, queryable primary store. Schema:
  events(id, ts_utc, event_type, correlation_id, agent_id, intent, message_id, payload_json)

JSONL (logs/events.jsonl) continues to be appended for grep/tail/quick-eyeball
workflows. Drop the mirror once a query CLI is mature.

Pulled from payload (when present) into indexed columns:
  - correlation_id   from payload.envelope.metadata.correlation_id, payload.metadata.correlation_id, etc.
  - agent_id         from payload.agent_id, payload.envelope.from_agent_id, etc.
  - intent           from payload.envelope.intent, payload.intent
  - message_id       from payload.envelope.message_id, payload.message_id
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    correlation_id  TEXT,
    agent_id        TEXT,
    intent          TEXT,
    message_id      TEXT,
    payload_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_ts          ON events(ts_utc);
CREATE INDEX IF NOT EXISTS ix_events_type        ON events(event_type);
CREATE INDEX IF NOT EXISTS ix_events_corr        ON events(correlation_id);
CREATE INDEX IF NOT EXISTS ix_events_agent       ON events(agent_id);
CREATE INDEX IF NOT EXISTS ix_events_intent      ON events(intent);
CREATE INDEX IF NOT EXISTS ix_events_message_id  ON events(message_id);
"""


def _extract(payload: Dict[str, Any], *paths: Tuple[str, ...]) -> Optional[str]:
    """
    Try a sequence of dotted-path lookups in payload, return the first hit
    that is a string. Each path is a tuple of dict keys.
    """
    for path in paths:
        cur: Any = payload
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and isinstance(cur, str):
            return cur
    return None


def _index_fields(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Pull the indexed fields out of a payload dict, regardless of nesting."""
    return {
        "correlation_id": _extract(
            payload,
            ("correlation_id",),
            ("envelope", "metadata", "correlation_id"),
            ("metadata", "correlation_id"),
            ("response", "metadata", "correlation_id"),
        ),
        "agent_id": _extract(
            payload,
            ("agent_id",),
            ("envelope", "from_agent_id"),
            ("from_agent_id",),
            ("response", "from_agent_id"),
        ),
        "intent": _extract(
            payload,
            ("intent",),
            ("envelope", "intent"),
            ("response", "intent"),
        ),
        "message_id": _extract(
            payload,
            ("message_id",),
            ("envelope", "message_id"),
            ("response", "message_id"),
        ),
    }


class EventLog:
    """
    Append-only event log.
    SQLite is primary; JSONL is mirrored for backward-compatible tail/grep.
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.log_dir / "events.jsonl"
        self.db_path = self.log_dir / "events.db"
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def append(self, event_type: str, payload: Dict[str, Any]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        idx = _index_fields(payload)
        payload_json = json.dumps(payload, separators=(",", ":"))

        # SQLite primary
        self._conn.execute(
            "INSERT INTO events (ts_utc, event_type, correlation_id, agent_id, intent, message_id, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, event_type, idx["correlation_id"], idx["agent_id"], idx["intent"], idx["message_id"], payload_json),
        )
        self._conn.commit()

        # JSONL mirror
        record = {"timestamp": ts, "event_type": event_type, "payload": payload}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")

    def read_all(self) -> List[Dict[str, Any]]:
        """Return all events from SQLite as dicts matching the JSONL shape."""
        cur = self._conn.execute(
            "SELECT ts_utc, event_type, payload_json FROM events ORDER BY id ASC"
        )
        return [
            {"timestamp": ts, "event_type": et, "payload": json.loads(pj)}
            for ts, et, pj in cur.fetchall()
        ]

    # Query helpers used by the CLI
    def query(
        self,
        event_type: Optional[str] = None,
        correlation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        intent: Optional[str] = None,
        message_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if event_type:
            clauses.append("event_type = ?"); params.append(event_type)
        if correlation_id:
            clauses.append("correlation_id = ?"); params.append(correlation_id)
        if agent_id:
            clauses.append("agent_id = ?"); params.append(agent_id)
        if intent:
            clauses.append("intent = ?"); params.append(intent)
        if message_id:
            clauses.append("message_id = ?"); params.append(message_id)
        if since:
            clauses.append("ts_utc >= ?"); params.append(since)
        if until:
            clauses.append("ts_utc <= ?"); params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT id, ts_utc, event_type, correlation_id, agent_id, intent, message_id, payload_json "
            f"FROM events{where} ORDER BY id ASC LIMIT ?"
        )
        params.append(limit)
        cur = self._conn.execute(sql, params)
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "correlation_id": r[3],
                "agent_id": r[4],
                "intent": r[5],
                "message_id": r[6],
                "payload": json.loads(r[7]),
            }
            for r in rows
        ]

    def stats(self) -> Dict[str, Any]:
        cur = self._conn.execute("SELECT COUNT(*) FROM events")
        total = cur.fetchone()[0]
        cur = self._conn.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY 2 DESC"
        )
        by_type = dict(cur.fetchall())
        cur = self._conn.execute(
            "SELECT correlation_id, COUNT(*) FROM events "
            "WHERE correlation_id IS NOT NULL GROUP BY correlation_id ORDER BY 2 DESC LIMIT 10"
        )
        top_correlations = dict(cur.fetchall())
        return {"total": total, "by_event_type": by_type, "top_correlations": top_correlations}


# Backward compat for any old code path that did `from storage import save_log`.
_default_log = EventLog()


def save_log(payload: Dict[str, Any]) -> None:
    _default_log.append("message_processed", payload)
