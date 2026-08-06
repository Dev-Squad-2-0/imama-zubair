"""
Day 4 - end-to-end test: book -> reschedule -> cancel

Exercises the full appointment lifecycle through api.py's granular
endpoints (the same ones n8n's workflow calls, in the same order), plus a
standalone regression check for the reschedule date-parsing bug this file
was written to catch.

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
      when running without those credentials.

Run from src/:
    python3 test_appointment_workflow.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

buggy_single_parse = parse_appointment_datetime(dual_date_text, now=now)
fixed_parse = parse_reschedule_datetime(dual_date_text, now=now)

check("detect_appointment_intent reads this as 'reschedule'",
      detect_appointment_intent(dual_date_text) == "reschedule")
check("parse_appointment_datetime alone still grabs the OLD date (documents why a dedicated parser is needed)",
      buggy_single_parse == datetime(2026, 8, 1, 10, 0))
check("parse_reschedule_datetime resolves to the NEW date (Aug 7, not Aug 1)",
      fixed_parse == datetime(2026, 8, 7, 12, 0))

# single-date reschedule sentences must behave identically to the old parser
simple_text = "Kal 5 baje reschedule kar dein."
check("parse_reschedule_datetime matches parse_appointment_datetime for a single-date sentence",
      parse_reschedule_datetime(simple_text, now=now) == parse_appointment_datetime(simple_text, now=now))

# booking path (single date) must be completely unaffected by the new parser
book_text = "Mujhe DHA Phase 6 mein August 10 ko 12 baje appointment book karni hai."
check("parse_appointment_datetime (booking path) unaffected by the new reschedule parser",
      parse_appointment_datetime(book_text, now=now) == datetime(2026, 8, 10, 12, 0))


if SKIP_LIVE_CALENDAR:
    print("\n[SKIPPED] SKIP_LIVE_CALENDAR is set - not exercising real Calendar/Gmail via TestClient.")
else:
    # -----------------------------------------------------------------------
    # 2. Full lifecycle through api.py's endpoints, in the same order and
    #    shape n8n's workflow calls them - real Calendar events, real Gmail
    #    sends, real CRM rows.
    # -----------------------------------------------------------------------
    print("\n=== 2. Book -> reschedule -> cancel, through api.py (TestClient, real side effects) ===")

    from fastapi.testclient import TestClient
    import api
    import crm_logger

    client = TestClient(api.app)
    SID = f"test-appt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    FUTURE_DATE = (datetime.now() + timedelta(days=30)).strftime("%B %d")  # e.g. "September 05"

    book_text = (
        f"Assalam o Alaikum. Mera naam Test Client hai. Mera budget 3 crore hai. "
        f"Mujhe DHA Phase 6 mein {FUTURE_DATE} ko 2 baje appointment book karni hai. "
        f"Mera number 03001112222 hai."
    )
    book_resp = client.post("/workflow/run", json={"session_id": SID, "customer_text": book_text}).json()
    check("book: /workflow/run reports booked=True", book_resp.get("booked") is True)
    check("book: real event_id returned", bool(book_resp.get("event_id")))
    booked_event_id = book_resp.get("event_id")

    email_step = next((s for s in book_resp.get("steps", []) if s["step"] == "email_notify"), None)
    check("book: email_notify step succeeded", email_step and email_step["result"].get("success") is True)

    if booked_event_id:
        # --- reschedule, dual-date sentence (the actual reported bug) ---
        new_date = (datetime.now() + timedelta(days=37)).strftime("%B %d")
        reschedule_text = (
            f"Meri {FUTURE_DATE} ki 2 baje ki appointment ko {new_date} ko 5 baje reschedule kar dein."
        )
        client.post("/intent", json={"session_id": SID, "customer_text": reschedule_text})
        pm = client.post("/property-match", json={"session_id": SID}).json()
        check("reschedule: /property-match exposes pending_appointment_event_id",
              pm.get("pending_appointment_event_id") == booked_event_id)

        resched_resp = client.post("/calendar/reschedule", json={
            "session_id": SID, "event_id": booked_event_id, "new_datetime_text": reschedule_text,
        }).json()
        check("reschedule: succeeds", resched_resp.get("success") is True)
        check("reschedule: moved to the NEW date, not the original one",
              new_date.split()[-1] in (resched_resp.get("new_start_datetime") or "")
              or str(int(new_date.split()[-1])) in (resched_resp.get("new_start_datetime") or ""))
        check("reschedule: response includes a usable 'appointment' dict for the email step",
              isinstance(resched_resp.get("appointment"), dict)
              and resched_resp["appointment"].get("client_name") == "Test Client")

        resched_email = client.post("/email/notify", json={
            "session_id": SID, "kind": "reschedule",
            "appointment": resched_resp.get("appointment"),
            "old_start_datetime": resched_resp.get("old_start_datetime"),
        }).json()
        check("reschedule: email_notify succeeds with the appointment dict /calendar/reschedule returned",
              resched_email.get("success") is True)

        # --- cancel ---
        cancel_text = "Meri appointment cancel kar dein please, plan change ho gaya hai."
        client.post("/intent", json={"session_id": SID, "customer_text": cancel_text})
        pm2 = client.post("/property-match", json={"session_id": SID}).json()
        check("cancel: /property-match still exposes the event id after a reschedule",
              pm2.get("pending_appointment_event_id") == booked_event_id)

        cancel_resp = client.post("/calendar/cancel", json={
            "session_id": SID, "event_id": booked_event_id, "reason": "plan change ho gaya hai",
        }).json()
        check("cancel: succeeds", cancel_resp.get("success") is True)
        check("cancel: response includes a usable 'appointment' dict for the email step",
              isinstance(cancel_resp.get("appointment"), dict)
              and cancel_resp["appointment"].get("client_name") == "Test Client")

        cancel_email = client.post("/email/notify", json={
            "session_id": SID, "kind": "cancel",
            "appointment": cancel_resp.get("appointment"),
            "reason": "plan change ho gaya hai",
        }).json()
        check("cancel: email_notify succeeds with the appointment dict /calendar/cancel returned",
              cancel_email.get("success") is True)

        # cancelling again proves the first cancel really deleted the event server-side
        recancel = client.post("/calendar/cancel", json={
            "session_id": SID, "event_id": booked_event_id, "reason": "double-cancel check",
        }).json()
        check("cancel: cancelling the same event_id again fails honestly (already deleted)",
              recancel.get("success") is False)

        # -------------------------------------------------------------------
        # 3. CRM trail sanity check
        # -------------------------------------------------------------------
        print("\n=== 3. CRM trail ===")
        logs = client.get(f"/crm/log/{SID}").json()["logs"]
        event_types = [l["event_type"] for l in logs]
        check("CRM: booking logged", "appointment_booked" in event_types)
        check("CRM: reschedule logged", "appointment_rescheduled" in event_types)
        check("CRM: cancellation logged", "appointment_cancelled" in event_types)
        check("CRM: no workflow_failed entries in a fully successful run",
              "workflow_failed" not in event_types and "workflow_failed_at_calendar" not in event_types)
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
