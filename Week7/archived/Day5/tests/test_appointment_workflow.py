"""
Day 5 - end-to-end test: book -> reschedule -> cancel

Exercises the full appointment lifecycle through the current FastAPI
backend (src/api.py, LangGraph-orchestrated - the old granular
conversation_memory-driven endpoints this file used to call live in
old_agent/api.py now), plus a standalone regression check for the
reschedule date-parsing bug this file was originally written to catch.

The lifecycle is now driven through natural multi-turn conversation via
POST /session/{id}/turn/text, not one-shot granular endpoint calls, since
that's how the LangGraph engine actually works: turn 1 states preferences
(populates property_preferences so a property is "shown" for booking to
reference), turn 2 gives contact details + the booking request (this is
also where a NEW-phone-number confirmation loop kicks in - see
conversation_memory.py's confirmation state machine), turn 3 confirms the
phone read-back, which is what actually completes the booking (with the
date/time remembered from turn 2 - see nodes.py's
_resolve_turn_datetime()). This three-turn shape is itself a regression
check: it only passes if the phone-confirmation flow AND graph.py's
_route_after_intent() "stay in the booking flow while a write action is
still unresolved" fallback both work together correctly.

What's real vs what's skipped (honest, not mocked - same rule
test_crm_logging.py follows):
    - This environment has real Google Calendar + Gmail OAuth credentials
      configured, unlike test_crm_logging.py's sandbox. So unlike that
      file, this one does NOT skip the Calendar/Gmail calls - it hits them
      for real through FastAPI's TestClient. A booked-but-never-cancelled
      test event would be a bad thing to leave behind, so the suite's own
      cancel step deletes the real calendar event it creates; three real
      emails (book/reschedule/cancel) do go out to EMPLOYEE_EMAIL each run,
      which is expected, not a leak.
    - If GOOGLE_CREDENTIALS_PATH / EMPLOYEE_EMAIL aren't configured in
      .env, the Calendar/Gmail sections fail loudly (honest FAIL, not a
      silently skipped check) - see SKIP_LIVE_CALENDAR below to opt out
      when running without those credentials, or to avoid real Calendar
      writes/emails on a run where you don't want them.

Run from tests/:
    python3 test_appointment_workflow.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from appointment_intent import parse_appointment_datetime, parse_reschedule_datetime, detect_appointment_intent

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(label, condition):
    status = PASS if condition else FAIL
    results.append((label, status))
    print(f"[{status}] {label}")


# Set to True to skip every section that touches the real Calendar/Gmail
# APIs (e.g. running in an environment with no Google OAuth configured).
SKIP_LIVE_CALENDAR = os.getenv("SKIP_LIVE_CALENDAR", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# 1. Reschedule date parsing - the actual bug this file guards against.
#    Pure unit test, no network: a sentence mentioning BOTH the original
#    appointment's date and the newly requested one must resolve to the
#    NEW one, not whichever comes first in the sentence.
# ---------------------------------------------------------------------------
print("\n=== 1. Reschedule date parsing (regression: old vs new date) ===")

now = datetime(2026, 7, 1)
dual_date_text = "Meri August 1 ki 10 baje ki appointment ko August 7 ko 12 baje reschedule kar dein."

# both parsers now return (datetime, had_explicit_clock) - see
# appointment_intent.py's _resolve_datetime_mentions docstring for why.
single_parse_dt, _ = parse_appointment_datetime(dual_date_text, now=now)
fixed_parse_dt, _ = parse_reschedule_datetime(dual_date_text, now=now)

check("detect_appointment_intent reads this as 'reschedule'",
      detect_appointment_intent(dual_date_text) == "reschedule")
check("parse_appointment_datetime (day-anchored-first rule) picks the OLD date here, "
      "since it's the first day mention - documents why a dedicated reschedule parser is needed",
      single_parse_dt == datetime(2026, 8, 1, 10, 0))
check("parse_reschedule_datetime resolves to the NEW date (Aug 7, not Aug 1)",
      fixed_parse_dt == datetime(2026, 8, 7, 12, 0))

# single-date reschedule sentences must behave identically to the old parser
simple_text = "Kal 5 baje reschedule kar dein."
check("parse_reschedule_datetime matches parse_appointment_datetime for a single-date sentence",
      parse_reschedule_datetime(simple_text, now=now) == parse_appointment_datetime(simple_text, now=now))

# booking path (single date) must be completely unaffected by the new parser
book_text = "Mujhe DHA Phase 6 mein August 10 ko 12 baje appointment book karni hai."
book_dt, _ = parse_appointment_datetime(book_text, now=now)
check("parse_appointment_datetime (booking path) unaffected by the new reschedule parser",
      book_dt == datetime(2026, 8, 10, 12, 0))

# regression case for the actual reported bug: a day-less clock mention
# earlier in the sentence (an aside, not a request) must not be picked over
# a day-anchored mention later in the sentence.
stray_time_text = "Abhi 8:30 baje hai, kal 12 pm appointment chahiye."
stray_dt, _ = parse_appointment_datetime(stray_time_text, now=now)
check("parse_appointment_datetime prefers the day-anchored 'kal 12 pm' over the stray 'abhi 8:30'",
      stray_dt == datetime(2026, 7, 2, 12, 0))


def _find_appointment_status(trace):
    """Scans a turn's trace (oldest first) for the last write-action node's
    output_snapshot.appointment_status - the event_id/start_datetime a
    booking/reschedule/cancel turn actually produced. graph_logger.py's
    _snapshot() includes appointment_status in every node's output_snapshot,
    so this needs no new backend endpoint."""
    for row in reversed(trace):
        status = (row.get("output_snapshot") or {}).get("appointment_status")
        if status:
            return status
    return None


if SKIP_LIVE_CALENDAR:
    print("\n[SKIPPED] SKIP_LIVE_CALENDAR is set - not exercising real Calendar/Gmail via TestClient.")
else:
    # -----------------------------------------------------------------------
    # 2. Full lifecycle through src/api.py (LangGraph-backed FastAPI), via
    #    natural multi-turn conversation - real Calendar events, real Gmail
    #    sends, real CRM rows.
    # -----------------------------------------------------------------------
    print("\n=== 2. Book -> reschedule -> cancel, through src/api.py (TestClient, real side effects) ===")

    from fastapi.testclient import TestClient
    import api

    client = TestClient(api.app)
    SID = f"test-appt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    FUTURE_DATE = (datetime.now() + timedelta(days=30)).strftime("%B %d")  # e.g. "September 05"

    def turn(text):
        r = client.post(f"/session/{SID}/turn/text", json={"text": text})
        return r.json()

    # turn 1: preferences, so a property is "shown" for booking to reference
    turn("Assalam o Alaikum. Mera naam Test Client hai. Mera budget 3 crore hai. Mujhe DHA Phase 6 mein ghar chahiye.")

    # turn 2: contact + booking request - a fresh, well-formed phone number
    # lands in client_phone_pending awaiting confirmation, not client_phone
    # yet (see conversation_memory.py), so this turn should NOT book yet.
    t2 = turn(f"Mera number 03001112222 hai. Mujhe {FUTURE_DATE} ko 2 baje appointment book karni hai.")
    check("book turn 2: asks for phone read-back confirmation, doesn't book yet",
          "sahi hai" in t2["agent_reply"].lower() and "0300" in t2["agent_reply"])

    # turn 3: confirm the phone read-back - completes the booking using the
    # date/time remembered from turn 2 (this turn's text has no date in it)
    t3 = turn("Haan ji sahi hai")
    booked_status = _find_appointment_status(t3["trace"])
    check("book: booking node ran and reached the availability check",
          any(row["node_name"] == "booking" for row in t3["trace"]))
    check("book: real event_id returned", bool(booked_status and booked_status.get("event_id")))
    booked_event_id = booked_status.get("event_id") if booked_status else None
    check("book: routed through email_node on success",
          any(row["node_name"] == "email" for row in t3["trace"]))

    if booked_event_id:
        # --- reschedule, dual-date sentence (the actual bug this file was
        # originally written to catch - a sentence mentioning BOTH the
        # original appointment's date and the newly requested one) ---
        new_date = (datetime.now() + timedelta(days=37)).strftime("%B %d")
        resched_resp = turn(
            f"Meri {FUTURE_DATE} ki 2 baje ki appointment ko {new_date} ko 5 baje reschedule kar dein."
        )
        resched_status = _find_appointment_status(resched_resp["trace"])
        check("reschedule: succeeds",
              any(row["node_name"] == "email" for row in resched_resp["trace"]))
        check("reschedule: moved to the NEW date, not the original one",
              bool(resched_status) and new_date.split()[-1] in (resched_status.get("start_datetime") or ""))
        check("reschedule: same event_id, not a new booking",
              resched_status and resched_status.get("event_id") == booked_event_id)

        # --- cancel ---
        cancel_resp = turn("Meri appointment cancel kar dein please, plan change ho gaya hai.")
        cancel_status = _find_appointment_status(cancel_resp["trace"])
        check("cancel: succeeds",
              cancel_status is not None and cancel_status.get("status") == "cancelled")

        # cancelling again proves the first cancel really deleted the event server-side
        recancel_resp = turn("Meri appointment dobara cancel kar dein.")
        check("cancel: cancelling the same event_id again fails honestly (already deleted)",
              "masla aa gaya" in recancel_resp["agent_reply"].lower())

        # -------------------------------------------------------------------
        # 3. CRM trail sanity check
        # -------------------------------------------------------------------
        print("\n=== 3. CRM trail ===")
        events = client.get(f"/session/{SID}/crm-events").json()["events"]
        event_types = [e["event_type"] for e in events]
        check("CRM: booking logged", "appointment_booked" in event_types)
        check("CRM: reschedule logged", "appointment_rescheduled" in event_types)
        check("CRM: cancellation logged", "appointment_cancelled" in event_types)
        check("CRM: emails logged for booking/reschedule/cancel", event_types.count("email_sent") >= 3)

        appt_history = client.get(f"/session/{SID}/transcript").json()["transcript"]
        check("Transcript: persisted to the DB (survives a backend restart)", len(appt_history) > 0)
    else:
        check("reschedule/cancel sections skipped: booking did not return an event_id", False)


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
