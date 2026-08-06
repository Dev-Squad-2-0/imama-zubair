"""
Day 4 - Task 5: CRM Logging

Every call session gets a row per event (call started, intent detected,
property matched, appointment booked/rescheduled/cancelled, emails sent,
failures) in a SQLite table, `crm_events`, inside the same
`db/knowledge_base.db` structured_retrieval.py already uses — one DB file
for the whole project rather than a second one to keep track of, following
the same _connect()/DB_PATH pattern that file already established.

api.py is the only caller. Every endpoint there logs through log_event()
after it does its own work, so /crm/log/{session_id} (get_logs_for_session)
gives a full, honest trail of what actually happened on a call: transcript
turns aren't duplicated here (that's ConversationMemory.history, in-memory
per session, not persisted — out of scope for Day 4), but everything that
touched an external system (Calendar, Gmail) or changed call state is.

Schema is deliberately generic (session_id, event_type, status, payload_json,
created_at) instead of one column per event type, since new event types
(follow-up reminders, CRM sync failures, etc.) shouldn't need a migration.
"""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "db", "knowledge_base.db")

_TABLE_READY = False


@dataclass
class CRMLogResult:
    success: bool
    log_id: Optional[int] = None
    error: Optional[str] = None


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn):
    """Created lazily on first use rather than a separate migration script,
    matching how the rest of Day 4 avoids adding new setup steps beyond
    what's already in the README. Safe to call every time — CREATE TABLE
    IF NOT EXISTS is a no-op after the first run."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'success',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_crm_events_session ON crm_events(session_id)"
    )
    conn.commit()
    _TABLE_READY = True


def _json_default(value):
    """Lets datetimes (start_datetime, etc. show up unchanged in a lot of
    the dicts api.py passes in) serialize instead of raising, since a
    logging call should never be the thing that crashes a turn."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def log_event(session_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None,
              status: str = "success") -> CRMLogResult:
    """Writes one CRM event row. Never raises — a logging failure should
    degrade to an honest CRMLogResult(success=False, ...) rather than take
    down the calling endpoint, matching the "explicit success flag, not an
    exception" contract api.py uses everywhere else."""
    try:
        conn = _connect()
        _ensure_table(conn)
        cur = conn.execute(
            "INSERT INTO crm_events (session_id, event_type, status, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                event_type,
                status,
                json.dumps(payload or {}, default=_json_default),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        log_id = cur.lastrowid
        conn.close()
        return CRMLogResult(success=True, log_id=log_id)
    except Exception as e:
        return CRMLogResult(success=False, error=str(e))


def get_logs_for_session(session_id: str) -> List[Dict[str, Any]]:
    """Full event trail for one call, oldest first — what /crm/log/{session_id}
    returns. Returns [] rather than raising if the table doesn't exist yet
    (a session that never logged anything, e.g. the DB was just created)."""
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT id, session_id, event_type, status, payload_json, created_at "
            "FROM crm_events WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    logs = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        logs.append({
            "id": row["id"],
            "session_id": row["session_id"],
            "event_type": row["event_type"],
            "status": row["status"],
            "payload": payload,
            "created_at": row["created_at"],
        })
    return logs


def get_recent_events(limit: int = 50) -> List[Dict[str, Any]]:
    """All sessions, most recent first. Not exposed as an API endpoint yet
    (not asked for in the Day 4 spec), but useful for a manual sanity check
    and for a future admin/ops view without a schema change."""
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT id, session_id, event_type, status, payload_json, created_at "
            "FROM crm_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "event_type": row["event_type"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
            "created_at": row["created_at"],
        }
        for row in rows
    ]


if __name__ == "__main__":
    sid = "smoke-test-session"
    print(log_event(sid, "call_started", {"client_phone": "0300-1234567"}))
    print(log_event(sid, "intent_detected", {"call_intent": "buyer_inquiry"}))
    print(log_event(sid, "calendar_failed", {"error": "token expired"}, status="failed"))

    print("\n-- Full trail for session --")
    for entry in get_logs_for_session(sid):
        print(entry)
