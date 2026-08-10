"""
Week 7 — Day 6 — Task 4: Production Monitoring

Tracks:
- average graph/API latency
- voice quality
- API failures
- Calendar failures
- email failures
- booking success
- RAG misses

The module is intentionally lightweight: SQLite only, no Prometheus/Grafana
dependency required for the capstone.

It preserves the function names already used by the project:
    record_graph_turn()
    record_api_request()
    record_voice_quality()
    record_rag_result()
    get_summary()
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv(
    "MONITORING_DB_PATH",
    str(BASE / "db" / "knowledge_base.db"),
)

_READY = False
_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    if not _table_exists(conn, table):
        return []
    return [
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    ]


def _first_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    lookup = {c.lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def _ensure(conn: sqlite3.Connection) -> None:
    global _READY
    if _READY:
        return

    with _LOCK:
        if _READY:
            return

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_service_metrics_name_time
            ON service_metrics(metric_name, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_service_metrics_session
            ON service_metrics(session_id, created_at)
            """
        )
        conn.commit()
        _READY = True


def record_metric(
    name: str,
    value: float,
    session_id: Optional[str] = None,
    status: str = "ok",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist one monitoring metric.

    Monitoring must never crash the voice agent, so failures are logged and
    returned as False instead of propagating into the conversation.
    """
    try:
        with _LOCK:
            conn = _connect()
            _ensure(conn)
            conn.execute(
                """
                INSERT INTO service_metrics(
                    session_id,
                    metric_name,
                    value,
                    status,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    name,
                    float(value),
                    status,
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            conn.close()
        return True

    except Exception as exc:
        print(f"[monitoring] failed to record {name}: {exc}")
        return False


# -------------------------------------------------------------------
# Metrics already called by the agent
# -------------------------------------------------------------------

def record_graph_turn(
    session_id: str,
    latency_ms: float,
    success: bool = True,
) -> bool:
    return record_metric(
        "graph_turn_latency_ms",
        latency_ms,
        session_id=session_id,
        status="ok" if success else "failed",
    )


def record_api_request(
    path: str,
    method: str,
    status_code: int,
    latency_ms: float,
    session_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> None:
    metadata = {
        "path": path,
        "method": method,
        "status_code": status_code,
    }
    if provider:
        metadata["provider"] = provider

    record_metric(
        "api_request_latency_ms",
        latency_ms,
        session_id=session_id,
        status="ok" if status_code < 400 else "failed",
        metadata=metadata,
    )

    if status_code >= 400:
        record_metric(
            "api_failure",
            1,
            session_id=session_id,
            status="failed",
            metadata=metadata,
        )


def record_api_failure(
    provider: str,
    error: Any,
    session_id: Optional[str] = None,
    operation: Optional[str] = None,
    status_code: Optional[int] = None,
) -> None:
    """Record failures from non-HTTP-client wrappers such as Groq/Gemini/Fish."""
    metadata = {
        "provider": provider,
        "error": str(error),
    }
    if operation:
        metadata["operation"] = operation
    if status_code is not None:
        metadata["status_code"] = status_code

    record_metric(
        "api_failure",
        1,
        session_id=session_id,
        status="failed",
        metadata=metadata,
    )


def record_voice_quality(
    session_id: str,
    stt_confidence: Optional[float] = None,
    tts_first_byte_ms: Optional[float] = None,
    tts_success: Optional[bool] = None,
    barge_in_success: Optional[bool] = None,
) -> None:
    if stt_confidence is not None:
        record_metric(
            "stt_confidence",
            stt_confidence,
            session_id=session_id,
            status="ok" if stt_confidence >= 0.70 else "low",
        )

    if tts_first_byte_ms is not None:
        record_metric(
            "tts_first_byte_ms",
            tts_first_byte_ms,
            session_id=session_id,
        )

    if tts_success is not None:
        record_metric(
            "tts_success",
            1 if tts_success else 0,
            session_id=session_id,
            status="ok" if tts_success else "failed",
        )

    if barge_in_success is not None:
        record_metric(
            "barge_in_success",
            1 if barge_in_success else 0,
            session_id=session_id,
            status="ok" if barge_in_success else "failed",
        )


def record_rag_result(
    session_id: str,
    hit_count: int,
    query: Optional[str] = None,
    top_distance: Optional[float] = None,
) -> None:
    metadata: Dict[str, Any] = {}
    if query:
        metadata["query"] = query
    if top_distance is not None:
        metadata["top_distance"] = top_distance

    record_metric(
        "rag_hit_count",
        hit_count,
        session_id=session_id,
        status="ok" if hit_count > 0 else "miss",
        metadata=metadata,
    )

    if hit_count <= 0:
        record_metric(
            "rag_miss",
            1,
            session_id=session_id,
            status="miss",
            metadata=metadata,
        )


# Optional explicit helpers. Existing nodes can continue to rely on crm_events.
def record_calendar_result(
    session_id: str,
    success: bool,
    operation: str,
    error: Optional[str] = None,
) -> None:
    record_metric(
        "calendar_operation",
        1 if success else 0,
        session_id=session_id,
        status="ok" if success else "failed",
        metadata={
            "operation": operation,
            "error": error,
        },
    )
    if not success:
        record_metric(
            "calendar_failure",
            1,
            session_id=session_id,
            status="failed",
            metadata={
                "operation": operation,
                "error": error,
            },
        )


def record_email_result(
    session_id: str,
    success: bool,
    error: Optional[str] = None,
) -> None:
    record_metric(
        "email_operation",
        1 if success else 0,
        session_id=session_id,
        status="ok" if success else "failed",
        metadata={"error": error},
    )
    if not success:
        record_metric(
            "email_failure",
            1,
            session_id=session_id,
            status="failed",
            metadata={"error": error},
        )


def record_booking_result(
    session_id: str,
    success: bool,
    operation: str = "book",
    event_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    record_metric(
        "booking_attempt",
        1,
        session_id=session_id,
        status="ok" if success else "failed",
        metadata={
            "operation": operation,
            "event_id": event_id,
            "error": error,
        },
    )
    record_metric(
        "booking_success",
        1 if success else 0,
        session_id=session_id,
        status="ok" if success else "failed",
        metadata={
            "operation": operation,
            "event_id": event_id,
            "error": error,
        },
    )


# -------------------------------------------------------------------
# Aggregation
# -------------------------------------------------------------------

def _scalar(
    conn: sqlite3.Connection,
    sql: str,
    args: tuple = (),
    default: float = 0,
):
    try:
        row = conn.execute(sql, args).fetchone()
        return row[0] if row and row[0] is not None else default
    except sqlite3.OperationalError:
        return default


def _metric_count(
    conn: sqlite3.Connection,
    metric_name: str,
    since: str,
    status: Optional[str] = None,
) -> int:
    if status is None:
        return int(
            _scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM service_metrics
                WHERE metric_name=? AND created_at>=?
                """,
                (metric_name, since),
            )
        )

    return int(
        _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM service_metrics
            WHERE metric_name=? AND status=? AND created_at>=?
            """,
            (metric_name, status, since),
        )
    )


def _crm_failure_count(
    conn: sqlite3.Connection,
    event_type: str,
    since: str,
) -> int:
    if not _table_exists(conn, "crm_events"):
        return 0

    columns = _columns(conn, "crm_events")
    event_col = _first_column(columns, ["event_type", "type", "event"])
    created_col = _first_column(
        columns,
        ["created_at", "timestamp", "logged_at"],
    )

    if not event_col:
        return 0

    if created_col:
        return int(
            _scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM crm_events
                WHERE {event_col}=? AND {created_col}>=?
                """,
                (event_type, since),
            )
        )

    return int(
        _scalar(
            conn,
            f"SELECT COUNT(*) FROM crm_events WHERE {event_col}=?",
            (event_type,),
        )
    )


def _appointment_counts(
    conn: sqlite3.Connection,
    since: str,
) -> Dict[str, int]:
    if not _table_exists(conn, "appointment_history"):
        return {"booked": 0, "rescheduled": 0, "cancelled": 0}

    columns = _columns(conn, "appointment_history")
    status_col = _first_column(columns, ["status"])
    created_col = _first_column(
        columns,
        ["created_at", "timestamp", "logged_at"],
    )

    if not status_col:
        return {"booked": 0, "rescheduled": 0, "cancelled": 0}

    result = {}
    for status in ("booked", "rescheduled", "cancelled"):
        if created_col:
            count = _scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM appointment_history
                WHERE {status_col}=? AND {created_col}>=?
                """,
                (status, since),
            )
        else:
            count = _scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM appointment_history
                WHERE {status_col}=?
                """,
                (status,),
            )
        result[status] = int(count)

    return result


def get_summary(window_minutes: int = 60) -> Dict[str, Any]:
    since = (datetime.now() - timedelta(minutes=window_minutes)).isoformat()

    conn = _connect()
    _ensure(conn)

    average_turn_latency = float(
        _scalar(
            conn,
            """
            SELECT AVG(value)
            FROM service_metrics
            WHERE metric_name='graph_turn_latency_ms'
              AND created_at>=?
            """,
            (since,),
        )
    )
    average_api_latency = float(
        _scalar(
            conn,
            """
            SELECT AVG(value)
            FROM service_metrics
            WHERE metric_name='api_request_latency_ms'
              AND created_at>=?
            """,
            (since,),
        )
    )

    average_stt_confidence = float(
        _scalar(
            conn,
            """
            SELECT AVG(value)
            FROM service_metrics
            WHERE metric_name='stt_confidence'
              AND created_at>=?
            """,
            (since,),
        )
    )
    average_tts_first_byte = float(
        _scalar(
            conn,
            """
            SELECT AVG(value)
            FROM service_metrics
            WHERE metric_name='tts_first_byte_ms'
              AND created_at>=?
            """,
            (since,),
        )
    )

    tts_total = _metric_count(conn, "tts_success", since)
    tts_successes = int(
        _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM service_metrics
            WHERE metric_name='tts_success'
              AND value=1
              AND created_at>=?
            """,
            (since,),
        )
    )

    # Voice quality is represented by real observable submetrics rather than
    # inventing one unverifiable subjective score.
    tts_success_rate = (
        round(100 * tts_successes / tts_total, 2)
        if tts_total else None
    )

    api_failures = _metric_count(conn, "api_failure", since)

    # Calendar/email failures can come from explicit monitoring OR from the
    # CRM events already written by current nodes.py. Use max rather than sum
    # to avoid double-counting if both paths log the same operation.
    explicit_calendar_failures = _metric_count(
        conn, "calendar_failure", since
    )
    crm_calendar_failures = _crm_failure_count(
        conn, "calendar_failed", since
    )
    calendar_failures = max(
        explicit_calendar_failures,
        crm_calendar_failures,
    )

    explicit_email_failures = _metric_count(
        conn, "email_failure", since
    )
    crm_email_failures = _crm_failure_count(
        conn, "email_failed", since
    )
    email_failures = max(
        explicit_email_failures,
        crm_email_failures,
    )

    rag_misses = _metric_count(conn, "rag_miss", since)
    rag_queries = _metric_count(conn, "rag_hit_count", since)
    rag_miss_rate = (
        round(100 * rag_misses / rag_queries, 2)
        if rag_queries else None
    )

    explicit_booking_attempts = _metric_count(
        conn, "booking_attempt", since
    )
    explicit_booking_successes = int(
        _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM service_metrics
            WHERE metric_name='booking_success'
              AND value=1
              AND created_at>=?
            """,
            (since,),
        )
    )

    appointment_counts = _appointment_counts(conn, since)
    booked = appointment_counts["booked"]

    if explicit_booking_attempts:
        booking_attempts = explicit_booking_attempts
        successful_bookings = explicit_booking_successes
        failed_bookings = max(0, booking_attempts - successful_bookings)
    else:
        # Current project nodes already persist successful bookings in
        # appointment_history and failed calendar operations in crm_events.
        successful_bookings = booked
        failed_bookings = calendar_failures
        booking_attempts = successful_bookings + failed_bookings

    booking_rate = (
        round(100 * successful_bookings / booking_attempts, 2)
        if booking_attempts else None
    )

    turn_count = _metric_count(
        conn, "graph_turn_latency_ms", since
    )

    conn.close()

    return {
        "window_minutes": window_minutes,
        "generated_at": datetime.now().isoformat(),
        "average_latency_ms": round(average_turn_latency, 2),
        "average_api_latency_ms": round(average_api_latency, 2),
        "turns_monitored": turn_count,
        "voice_quality": {
            "average_stt_confidence": round(
                average_stt_confidence, 4
            ) if average_stt_confidence else None,
            "average_tts_first_byte_ms": round(
                average_tts_first_byte, 2
            ) if average_tts_first_byte else None,
            "tts_successful": tts_successes,
            "tts_total": tts_total,
            "tts_success_rate_percent": tts_success_rate,
        },
        "api_failures": api_failures,
        "calendar_failures": calendar_failures,
        "email_failures": email_failures,
        "booking_success": {
            "successful": successful_bookings,
            "failed": failed_bookings,
            "attempts": booking_attempts,
            "rate_percent": booking_rate,
        },
        "rag": {
            "queries": rag_queries,
            "misses": rag_misses,
            "miss_rate_percent": rag_miss_rate,
        },
        # Explicit top-level field because Task 4 wording asks for RAG misses.
        "rag_misses": rag_misses,
        "appointment_activity": appointment_counts,
    }


def get_recent_failures(
    window_minutes: int = 60,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    since = (datetime.now() - timedelta(minutes=window_minutes)).isoformat()

    conn = _connect()
    _ensure(conn)

    rows = conn.execute(
        """
        SELECT *
        FROM service_metrics
        WHERE created_at>=?
          AND (
              status IN ('failed', 'miss')
              OR metric_name IN (
                  'api_failure',
                  'calendar_failure',
                  'email_failure',
                  'rag_miss'
              )
          )
        ORDER BY id DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()
    conn.close()

    failures = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(
                item.pop("metadata_json", "{}")
            )
        except Exception:
            item["metadata"] = {}
        failures.append(item)

    return failures
