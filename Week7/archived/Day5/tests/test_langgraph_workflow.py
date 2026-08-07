"""
Day 5 - end-to-end test for the LangGraph workflow (Tasks 1-5).

Same "honest, not mocked" convention Day 4's test_appointment_workflow.py
established: real Google Calendar events, real Gmail sends, run through
graph.run_turn() exactly as a live call would use it. Set
SKIP_LIVE_CALENDAR=1 to skip the sections that need live Google OAuth
credentials.

Run from tests/:
    python3 test_langgraph_workflow.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(label, condition):
    status = PASS if condition else FAIL
    results.append((label, status))
    print(f"[{status}] {label}")


SKIP_LIVE_CALENDAR = os.getenv("SKIP_LIVE_CALENDAR", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# 1. Reschedule date-parsing regression (pure unit, no network) - same bug
#    fix test_appointment_workflow.py guards, now also exercised through
#    the graph itself in section 6 below.
# ---------------------------------------------------------------------------
print("\n=== 1. Reschedule date parsing regression ===")
from appointment_intent import parse_reschedule_datetime

now = datetime(2026, 7, 1)
dual_date_text = "Meri August 1 ki 10 baje ki appointment ko August 7 ko 12 baje reschedule kar dein."
resched_dt, _ = parse_reschedule_datetime(dual_date_text, now=now)
check("parse_reschedule_datetime resolves to the NEW date, not the old one",
      resched_dt == datetime(2026, 8, 7, 12, 0))


# ---------------------------------------------------------------------------
# 2. Task 1 / Task 2: state shape + graph routing basics
# ---------------------------------------------------------------------------
print("\n=== 2. Graph structure (Task 1 state design / Task 2 routing) ===")
import graph

SID = f"test-langgraph-{datetime.now().strftime('%Y%m%d%H%M%S')}"
reply, trace = graph.run_turn(SID, "")
check("greeting turn returns the persona opening line", "Assalam" in reply)
check("greeting turn's trace has exactly one node (greeting)", [t["node_name"] for t in trace] == ["greeting"])

state = graph.get_session_state(SID)
check("AgentState has all Task 1 required fields", all(
    k in state for k in ("conversation_history", "user_profile", "property_preferences",
                          "intent", "tool_outputs", "appointment_status")
))


# ---------------------------------------------------------------------------
# 3. Task 4: never recommend an unavailable property
# ---------------------------------------------------------------------------
print("\n=== 3. Recommendation guardrail ===")
reply, trace = graph.run_turn(SID, "Mera budget 3 crore hai, Lahore mein ghar chahiye buy karne ke liye.")
check("routed through recommendation node", "recommendation" in [t["node_name"] for t in trace])
state = graph.get_session_state(SID)
candidates = state["tool_outputs"].get("last_recommendations", [])
check("recommendation returned at least one candidate", len(candidates) > 0)
check("every recommended property has status == 'available'",
      all(c.get("status") == "available" for c in candidates))


# ---------------------------------------------------------------------------
# 4. Task 4: ask for clarification instead of guessing (missing info)
# ---------------------------------------------------------------------------
print("\n=== 4. Booking guardrail: missing info -> clarification, not a guess ===")
SID2 = f"test-langgraph-missing-{datetime.now().strftime('%Y%m%d%H%M%S')}"
graph.run_turn(SID2, "")
reply, trace = graph.run_turn(SID2, "Mujhe appointment book karni hai.")
check("routed through booking node", "booking" in [t["node_name"] for t in trace])
state2 = graph.get_session_state(SID2)
check("clarification_needed is True when required info is missing", state2["clarification_needed"] is True)
check("missing_fields is non-empty", len(state2["missing_fields"]) > 0)
check("no appointment was created (appointment_status still None)", state2["appointment_status"] is None)


if SKIP_LIVE_CALENDAR:
    print("\n[SKIPPED] SKIP_LIVE_CALENDAR is set - not exercising real Calendar/Gmail.")
else:
    import calendar_integration as cal

    # -----------------------------------------------------------------------
    # 5. Task 4: never book an unavailable slot
    # -----------------------------------------------------------------------
    print("\n=== 5. Booking guardrail: never book an unavailable slot ===")
    blocker_start = (datetime.now() + timedelta(days=45)).replace(hour=11, minute=0, second=0, microsecond=0)
    blocker = cal.create_appointment_event(cal.AppointmentDetails(
        client_name="Blocker Event", client_phone="03000000000",
        property_title="Blocker Slot", property_id=None, start_datetime=blocker_start,
    ))
    check("setup: blocker event created to occupy a slot", blocker.success)

    if blocker.success:
        SID3 = f"test-langgraph-conflict-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        graph.run_turn(SID3, "")
        graph.run_turn(SID3, "Mera budget 3 crore hai, DHA Phase 6 mein ghar chahiye.")

        month_day = blocker_start.strftime("%B %d")
        hour_12 = str(int(blocker_start.strftime("%I")))
        book_text = (
            f"Mera naam Test Conflict hai. Mera number 03001234567 hai. Mujhe "
            f"{month_day} ko {hour_12} baje appointment book karni hai."
        )
        reply, trace = graph.run_turn(SID3, book_text)
        state3 = graph.get_session_state(SID3)
        check("conflicting slot: booking node ran", "booking" in [t["node_name"] for t in trace])
        check("conflicting slot: clarification_needed True (slot rejected, not booked)",
              state3["clarification_needed"] is True)
        check("conflicting slot: no appointment_status was set", state3["appointment_status"] is None)
        check("conflicting slot: email node never ran (write action did not succeed)",
              "email" not in [t["node_name"] for t in trace])

        cleanup = cal.cancel_appointment_event(blocker.event_id, "test cleanup")
        check("cleanup: blocker event cancelled", cleanup.success)

    # -----------------------------------------------------------------------
    # 6. Full lifecycle through the graph: book -> reschedule -> cancel -> goodbye
    # -----------------------------------------------------------------------
    print("\n=== 6. Full lifecycle through the graph ===")
    SID4 = f"test-langgraph-lifecycle-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    graph.run_turn(SID4, "")

    future = datetime.now() + timedelta(days=50)
    book_date = future.strftime("%B %d")
    prefs_text = (
        "Assalam o Alaikum. Mera naam Langgraph Test hai. Mera budget 3 crore hai. "
        "Mujhe DHA Phase 6 mein ghar chahiye. Mera number 03219998877 hai."
    )
    graph.run_turn(SID4, prefs_text)

    book_text = f"Mujhe {book_date} ko 3 baje appointment book karni hai."
    reply, trace = graph.run_turn(SID4, book_text)
    state4 = graph.get_session_state(SID4)
    check("lifecycle: booking succeeded",
          state4["appointment_status"] is not None and state4["appointment_status"].get("status") == "booked")
    check("lifecycle: routed through email after booking", "email" in [t["node_name"] for t in trace])
    check("lifecycle: email sent", state4["tool_outputs"].get("last_email", {}).get("success") is True)

    if state4["appointment_status"]:
        new_date = (future + timedelta(days=7)).strftime("%B %d")
        reschedule_text = f"Meri {book_date} ki 3 baje ki appointment ko {new_date} ko 5 baje reschedule kar dein."
        reply, trace = graph.run_turn(SID4, reschedule_text)
        state4 = graph.get_session_state(SID4)
        check("lifecycle: reschedule succeeded", state4["appointment_status"].get("status") == "rescheduled")
        check("lifecycle: reschedule moved to the NEW date, not the original",
              new_date.split()[-1].lstrip("0") in state4["appointment_status"]["start_datetime"])
        check("lifecycle: routed through email after reschedule", "email" in [t["node_name"] for t in trace])

        cancel_text = "Meri appointment cancel kar dein please, plan change ho gaya hai."
        reply, trace = graph.run_turn(SID4, cancel_text)
        state4 = graph.get_session_state(SID4)
        check("lifecycle: cancel succeeded", state4["appointment_status"].get("status") == "cancelled")
        check("lifecycle: routed through email after cancel", "email" in [t["node_name"] for t in trace])

        reply, trace = graph.run_turn(SID4, "Shukriya, Allah Hafiz.")
        check("lifecycle: goodbye turn routes through intent_detection then goodbye",
              [t["node_name"] for t in trace] == ["intent_detection", "goodbye"])


# ---------------------------------------------------------------------------
# 7. Task 5: annotated execution trace
# ---------------------------------------------------------------------------
print("\n=== 7. Task 5: state logging / execution trace ===")
from graph_logger import get_execution_trace

full_trace = get_execution_trace(SID)
check("get_execution_trace returns a non-empty trace for the session", len(full_trace) > 0)
check("every trace row has a duration and annotation field",
      all("duration_ms" in row and "annotation" in row for row in full_trace))
check("trace rows are chronologically ordered", full_trace == sorted(full_trace, key=lambda r: r["id"]))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n=== Summary ===")
passed = sum(1 for _, s in results if s == PASS)
failed = sum(1 for _, s in results if s == FAIL)
print(f"{passed} passed, {failed} failed, {len(results)} total")
if failed:
    print("\nFailed checks:")
    for label, status in results:
        if status == FAIL:
            print(f"  - {label}")
    sys.exit(1)
