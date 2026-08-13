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

Task 5 adds four purpose-built tables on top of crm_events, in the same
DB file (crm_events itself is untouched):

    call_transcripts     - every customer turn, per session. api.py already
                            sees the text at /intent, this just persists it -
                            ConversationMemory.history is in-process only and
                            is lost when the session dict entry goes away.
    client_preferences   - one row per client_phone, upserted from
                            ConversationMemory.slots so a returning caller's
                            budget/area/purpose is known before they repeat it.
    appointment_history  - one row per booked/rescheduled/cancelled
                            appointment, keyed by client_phone. Separate from
                            crm_events because a CRM screen wants "this
                            client's appointments", not "everything that
                            happened on event_id X".
    follow_up_reminders  - reminders created when a call doesn't end in a
                            booking (or any other workflow reason), with a
                            get_due_reminders() query a scheduled n8n trigger
                            can poll.
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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS call_transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_session ON call_transcripts(session_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS client_preferences (
            client_phone TEXT PRIMARY KEY,
            client_name TEXT,
            budget INTEGER,
            city TEXT,
            area TEXT,
            bedrooms INTEGER,
            property_type TEXT,
            purpose TEXT,
            last_session_id TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS appointment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            client_phone TEXT,
            client_name TEXT,
            property_id INTEGER,
            property_title TEXT,
            start_datetime TEXT,
            status TEXT NOT NULL,
            event_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_appt_history_phone ON appointment_history(client_phone)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS follow_up_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            client_phone TEXT,
            client_name TEXT,
            reason TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON follow_up_reminders(status, due_at)"
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


# ---------------------------------------------------------------------------
# Task 5: Call transcripts
# ---------------------------------------------------------------------------

def log_transcript_turn(session_id: str, speaker: str, text: str) -> CRMLogResult:
    """One row per turn. speaker is 'customer' or 'agent'. Never raises,
    same contract as log_event() - a transcript-logging failure shouldn't
    take down the call."""
    try:
        conn = _connect()
        _ensure_table(conn)
        cur = conn.execute(
            "INSERT INTO call_transcripts (session_id, speaker, text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, speaker, text, datetime.now().isoformat()),
        )
        conn.commit()
        log_id = cur.lastrowid
        conn.close()
        return CRMLogResult(success=True, log_id=log_id)
    except Exception as e:
        return CRMLogResult(success=False, error=str(e))


def get_transcript(session_id: str) -> List[Dict[str, Any]]:
    """Full transcript for one call, oldest first."""
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT id, session_id, speaker, text, created_at FROM call_transcripts "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Task 5: Client preferences
# ---------------------------------------------------------------------------

def upsert_client_preferences(session_id: str, client_phone: Optional[str],
                               slots: Dict[str, Any]) -> CRMLogResult:
    """Saves/updates the caller's known preferences keyed by phone number,
    so a returning caller (call_intent 'returning_customer') doesn't have
    to re-state budget/area/purpose. Silently no-ops (success=False, no
    exception) if the phone isn't known yet - preferences without a stable
    key to store them under aren't useful across calls, only within this
    one (ConversationMemory.slots already covers that in-call case)."""
    if not client_phone:
        return CRMLogResult(success=False, error="client_phone not known yet")
    try:
        conn = _connect()
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO client_preferences
                (client_phone, client_name, budget, city, area, bedrooms,
                 property_type, purpose, last_session_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_phone) DO UPDATE SET
                client_name = COALESCE(excluded.client_name, client_preferences.client_name),
                budget = COALESCE(excluded.budget, client_preferences.budget),
                city = COALESCE(excluded.city, client_preferences.city),
                area = COALESCE(excluded.area, client_preferences.area),
                bedrooms = COALESCE(excluded.bedrooms, client_preferences.bedrooms),
                property_type = COALESCE(excluded.property_type, client_preferences.property_type),
                purpose = COALESCE(excluded.purpose, client_preferences.purpose),
                last_session_id = excluded.last_session_id,
                updated_at = excluded.updated_at
            """,
            (
                client_phone,
                slots.get("client_name"),
                slots.get("budget"),
                slots.get("city"),
                slots.get("area"),
                slots.get("bedrooms"),
                slots.get("property_type"),
                slots.get("purpose"),
                session_id,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        return CRMLogResult(success=True)
    except Exception as e:
        return CRMLogResult(success=False, error=str(e))


def get_client_preferences(client_phone: str) -> Optional[Dict[str, Any]]:
    """Returns None (not a dict of Nones) if this client has no saved
    preferences yet, so callers can tell "unknown client" from "known
    client, nothing set" without inspecting every field."""
    try:
        conn = _connect()
        _ensure_table(conn)
        row = conn.execute(
            "SELECT * FROM client_preferences WHERE client_phone = ?", (client_phone,),
        ).fetchone()
        conn.close()
    except Exception:
        return None
    return dict(row) if row else None


def get_all_clients() -> List[Dict[str, Any]]:
    """Returns all clients in the client_preferences table."""
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM client_preferences ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Task 5: Appointment history
# ---------------------------------------------------------------------------

def log_appointment_history(session_id: str, status: str, client_phone: Optional[str] = None,
                             client_name: Optional[str] = None, property_id: Optional[int] = None,
                             property_title: Optional[str] = None,
                             start_datetime: Optional[str] = None,
                             event_id: Optional[str] = None) -> CRMLogResult:
    """One row per booked/rescheduled/cancelled appointment. status is a
    free string ('booked', 'rescheduled', 'cancelled') rather than an enum
    column so it stays consistent with the rest of the schema's generic-
    over-rigid choice."""
    try:
        conn = _connect()
        _ensure_table(conn)
        cur = conn.execute(
            """
            INSERT INTO appointment_history
                (session_id, client_phone, client_name, property_id, property_title,
                 start_datetime, status, event_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, client_phone, client_name, property_id, property_title,
             start_datetime, status, event_id, datetime.now().isoformat()),
        )
        conn.commit()
        log_id = cur.lastrowid
        conn.close()
        return CRMLogResult(success=True, log_id=log_id)
    except Exception as e:
        return CRMLogResult(success=False, error=str(e))


def _normalize_phone(phone: str) -> str:
    """Strip country code prefix and formatting so +923022356799,
    923022356799, and 03022356799 all produce the same 11-digit
    local form (03XXXXXXXXX). Vapi sends E.164 (+92...) while the
    app stores local (03...) — without this, every cross-call CRM
    lookup silently returns nothing and the user is forced to repeat
    all their details on every call."""
    import re
    digits = re.sub(r"[^\d]", "", phone or "")
    # +923022356799 -> 923022356799 -> 03022356799
    if digits.startswith("92") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def get_appointment_history(client_phone: str) -> List[Dict[str, Any]]:
    """All appointments (booked/rescheduled/cancelled) for one client,
    oldest first. Normalizes both the query number and stored numbers
    so +923022356799 matches a record stored as 03022356799."""
    try:
        conn = _connect()
        _ensure_table(conn)
        normalized = _normalize_phone(client_phone)
        # Try exact match first (fast path).
        rows = conn.execute(
            "SELECT * FROM appointment_history WHERE client_phone = ? ORDER BY id ASC",
            (client_phone,),
        ).fetchall()
        if not rows and normalized != client_phone:
            # Retry with normalized form (strips +92 prefix / dashes).
            rows = conn.execute(
                "SELECT * FROM appointment_history WHERE client_phone = ? ORDER BY id ASC",
                (normalized,),
            ).fetchall()
        if not rows:
            # Last-resort: scan all rows and compare normalized forms.
            # Slightly more expensive but ensures a format difference
            # (e.g. Vapi sending +92 vs app storing 03) is never a
            # silent lookup failure.
            all_rows = conn.execute(
                "SELECT * FROM appointment_history ORDER BY id ASC"
            ).fetchall()
            rows = [
                r for r in all_rows
                if _normalize_phone(r["client_phone"] or "") == normalized
            ]
        conn.close()
    except Exception:
        return []
    return [dict(row) for row in rows]


def get_all_appointments() -> List[Dict[str, Any]]:
    """Returns all appointments from the history table."""
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM appointment_history ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Task 5: Follow-up reminders
# ---------------------------------------------------------------------------

def create_follow_up_reminder(session_id: str, reason: str, due_at: str,
                               client_phone: Optional[str] = None,
                               client_name: Optional[str] = None) -> CRMLogResult:
    """due_at is an ISO datetime string the caller computes (e.g.
    (datetime.now() + timedelta(days=2)).isoformat()) - kept as a plain
    param rather than a timedelta so this stays framework-agnostic for
    whatever schedules the actual outbound call/email later (n8n Cron node
    polling get_due_reminders(), most likely)."""
    try:
        conn = _connect()
        _ensure_table(conn)
        cur = conn.execute(
            """
            INSERT INTO follow_up_reminders
                (session_id, client_phone, client_name, reason, due_at, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (session_id, client_phone, client_name, reason, due_at, datetime.now().isoformat()),
        )
        conn.commit()
        log_id = cur.lastrowid
        conn.close()
        return CRMLogResult(success=True, log_id=log_id)
    except Exception as e:
        return CRMLogResult(success=False, error=str(e))


def get_due_reminders(as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    """Pending reminders whose due_at has passed - what an n8n Cron trigger
    would poll to know who to call/email next. as_of defaults to now();
    accepting it as a param makes this deterministically testable."""
    as_of = as_of or datetime.now().isoformat()
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM follow_up_reminders WHERE status = 'pending' AND due_at <= ? "
            "ORDER BY due_at ASC",
            (as_of,),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [dict(row) for row in rows]


def get_all_reminders() -> List[Dict[str, Any]]:
    """Returns all follow-up reminders, regardless of status."""
    try:
        conn = _connect()
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM follow_up_reminders ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [dict(row) for row in rows]


def mark_reminder_done(reminder_id: int, status: str = "done") -> CRMLogResult:
    """Marks a reminder 'done' (default) or 'cancelled' so it stops showing
    up in get_due_reminders(). Rows are never deleted, keeping a full
    follow-up history per client."""
    try:
        conn = _connect()
        _ensure_table(conn)
        conn.execute(
            "UPDATE follow_up_reminders SET status = ? WHERE id = ?",
            (status, reminder_id),
        )
        conn.commit()
        conn.close()
        return CRMLogResult(success=True, log_id=reminder_id)
    except Exception as e:
        return CRMLogResult(success=False, error=str(e))


if __name__ == "__main__":
    sid = "smoke-test-session"
    print(log_event(sid, "call_started", {"client_phone": "0300-1234567"}))
    print(log_event(sid, "intent_detected", {"call_intent": "buyer_inquiry"}))
    print(log_event(sid, "calendar_failed", {"error": "token expired"}, status="failed"))

    print("\n-- Full trail for session --")
    for entry in get_logs_for_session(sid):
        print(entry)

    print("\n-- Task 5 stores --")
    print(log_transcript_turn(sid, "customer", "Budget 3 crore hai, DHA mein chahiye"))
    print(upsert_client_preferences(sid, "0300-1234567",
                                     {"client_name": "Ahmed", "budget": 30_000_000,
                                      "city": "Lahore", "area": "DHA Phase 6", "purpose": "buy"}))
    print(get_client_preferences("0300-1234567"))
    print(log_appointment_history(sid, "booked", client_phone="0300-1234567", client_name="Ahmed",
                                   property_title="DHA Phase 6 - 5 Marla", event_id="evt_123"))
    print(get_appointment_history("0300-1234567"))
    print(create_follow_up_reminder(sid, "No booking this call, follow up",
                                     due_at="2020-01-01T00:00:00", client_phone="0300-1234567"))
    print(get_due_reminders())
