"""
Day 5 - Task 5: State Logging

Every LangGraph node in this project is wrapped with @traced_node before
it's registered on the graph (see graph.py) - built first, per the brief,
so nothing gets added to the graph without being traced from day one.

Two things happen on every node transition:
    1. A live "entering/exiting" line printed to the terminal as it
       happens - this is the same plumbing the later live-microphone phase
       reuses to show what the agent is doing while a turn is in flight.
    2. An annotated row written to a new `graph_traces` table in the same
       db/knowledge_base.db Day 4's crm_logger.py already uses (same
       _connect()/_ensure_table() pattern, kept as its own table rather
       than folded into crm_events since a node-transition trace is a
       different shape/purpose than a CRM event).

LangGraph node convention used throughout this project: a node function
receives the full current state and returns a dict of ONLY the keys it
wants to change - LangGraph merges that into the real state itself. This
module's snapshotting has to respect that: the "output" logged for a node
is state merged with its partial update, not the raw return value.
"""

import json
import os
import sqlite3
import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "db", "knowledge_base.db")

_TABLE_READY = False


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn):
    global _TABLE_READY
    if _TABLE_READY:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_id INTEGER NOT NULL,
            node_name TEXT NOT NULL,
            entered_at TEXT NOT NULL,
            exited_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            input_snapshot_json TEXT NOT NULL,
            output_snapshot_json TEXT NOT NULL,
            annotation TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_traces_session_turn ON graph_traces(session_id, turn_id)"
    )
    conn.commit()
    _TABLE_READY = True


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    """A small, loggable slice of state - the fields that actually change
    turn to turn, not the full conversation_history/tool_outputs blobs
    (those get large fast and aren't what makes a trace readable; the
    annotation plus these slot/intent/status deltas are)."""
    return {
        "intent": state.get("intent"),
        "property_preferences": state.get("property_preferences"),
        "appointment_status": state.get("appointment_status"),
        "missing_fields": state.get("missing_fields"),
        "clarification_needed": state.get("clarification_needed"),
        "agent_reply": state.get("agent_reply"),
    }


def log_node_transition(session_id: str, turn_id: int, node_name: str,
                         entered_at: str, exited_at: str, duration_ms: int,
                         input_state: Dict[str, Any], output_state: Dict[str, Any],
                         annotation: str = "") -> None:
    """Never raises - a logging failure shouldn't take down a conversation
    turn, matching crm_logger.py's own contract."""
    try:
        conn = _connect()
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO graph_traces (session_id, turn_id, node_name, entered_at, exited_at, "
            "duration_ms, input_snapshot_json, output_snapshot_json, annotation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, turn_id, node_name, entered_at, exited_at, duration_ms,
                json.dumps(input_state, default=_json_default),
                json.dumps(output_state, default=_json_default),
                annotation,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [graph_logger] failed to persist trace for node {node_name!r}: {e}")


def traced_node(name: str, annotate: Optional[Callable[[Dict, Dict], str]] = None):
    """Decorator for a node function `def fn(state) -> dict` (a partial
    state update, per LangGraph convention). annotate, if given, computes a
    short human-readable note from (input_state, merged_output_state) for
    the trace - e.g. "booked event evt_123" or "slot unavailable, asked to
    clarify" - Task 5 asks for *annotated* traces, not a bare node-name
    list, so the note is what makes a row worth reading later."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            session_id = state.get("session_id", "unknown")
            turn_id = state.get("turn_id", 0)
            trace_so_far = list(state.get("node_trace", []))
            input_snapshot = _snapshot(state)

            entered_at = datetime.now()
            print(f"  -> [{session_id}] entering node: {name}")
            t0 = time.monotonic()

            update = fn(state) or {}

            duration_ms = int((time.monotonic() - t0) * 1000)
            exited_at = datetime.now()
            merged_preview = {**state, **update}

            note = ""
            if annotate:
                try:
                    note = annotate(state, merged_preview) or ""
                except Exception:
                    note = ""

            line = f"  <- [{session_id}] exiting node: {name} ({duration_ms}ms)"
            if note:
                line += f" - {note}"
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("ascii", "replace").decode("ascii"))

            update = dict(update)
            update["node_trace"] = trace_so_far + [name]

            log_node_transition(
                session_id, turn_id, name,
                entered_at.isoformat(), exited_at.isoformat(), duration_ms,
                input_snapshot, _snapshot(merged_preview), note,
            )
            return update
        return wrapper
    return decorator


def get_execution_trace(session_id: str, turn_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Full annotated trace for a session (or one turn if turn_id is given),
    oldest first - node sequence, per-node timings, and the annotation/
    snapshot deltas recorded at each step."""
    try:
        conn = _connect()
        _ensure_table(conn)
        if turn_id is not None:
            rows = conn.execute(
                "SELECT * FROM graph_traces WHERE session_id = ? AND turn_id = ? ORDER BY id ASC",
                (session_id, turn_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM graph_traces WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        conn.close()
    except Exception:
        return []

    traces = []
    for row in rows:
        traces.append({
            "id": row["id"], "session_id": row["session_id"], "turn_id": row["turn_id"],
            "node_name": row["node_name"], "entered_at": row["entered_at"], "exited_at": row["exited_at"],
            "duration_ms": row["duration_ms"],
            "input_snapshot": json.loads(row["input_snapshot_json"]),
            "output_snapshot": json.loads(row["output_snapshot_json"]),
            "annotation": row["annotation"],
        })
    return traces


if __name__ == "__main__":
    # Manual smoke test - traces a couple of fake node calls and reads them back.
    @traced_node("sample_node", annotate=lambda inp, out: f"reply set to {out.get('agent_reply')!r}")
    def sample_node(state):
        return {"agent_reply": "hello from sample_node"}

    fake_state = {"session_id": "smoke-test", "turn_id": 1, "node_trace": []}
    result = sample_node(fake_state)
    print("\nReturned update:", result)

    print("\nStored trace:")
    for row in get_execution_trace("smoke-test", 1):
        print(row)
