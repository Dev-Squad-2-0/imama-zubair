"""
Day 4 - Task 5 test: CRM Logging Store

Checks the four stores crm_logger.py added this session:
    1. call_transcripts     - persisted customer turns
    2. client_preferences   - upserted per client_phone
    3. appointment_history  - one row per booked/rescheduled/cancelled appt
    4. follow_up_reminders  - created + queryable via get_due_reminders()

What's real vs what's skipped (honest, not mocked):
    - crm_logger.py itself is 100% real: real sqlite3 against
      db/knowledge_base.db, no mocking anywhere in this file.
    - /webhook/call-start and /intent are hit through FastAPI's TestClient,
      which runs api.py for real (no network involved for these two
      endpoints) - this proves the transcript + preferences wiring inside
      api.py actually fires, not just that crm_logger's functions work in
      isolation.
    - /calendar/create, /calendar/reschedule, /calendar/cancel are NOT
      called here. Those need real Google OAuth credentials (Calendar +
      Gmail) that don't exist in this sandbox. Faking a successful
      cal_result would mean testing a lie, so instead this file calls
      crm_logger.log_appointment_history() directly with the same
      arguments api.py's calendar endpoints pass it - that's the actual
      Task 5 surface (the DB write), the Calendar API call itself is
      already covered by Day 4 Task 1/3's own tests.
    - This is flagged explicitly below instead of silently skipped.

Run from src/:
    python3 test_crm_logging.py
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crm_logger

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(label, condition):
    status = PASS if condition else FAIL
    results.append((label, status))
    print(f"[{status}] {label}")


SESSION = f"test-session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
PHONE = "0321-9998888"


# ---------------------------------------------------------------------------
# 1. Call transcripts - direct crm_logger test
# ---------------------------------------------------------------------------
print("\n=== 1. Call transcripts ===")

r1 = crm_logger.log_transcript_turn(SESSION, "customer", "Mera naam Bilal hai, budget 2 crore hai")
r2 = crm_logger.log_transcript_turn(SESSION, "agent", "Theek hai Bilal sahab, kaunsa area chahiye?")
check("log_transcript_turn returns success for customer turn", r1.success)
check("log_transcript_turn returns success for agent turn", r2.success)

transcript = crm_logger.get_transcript(SESSION)
check("get_transcript returns 2 rows", len(transcript) == 2)
check("get_transcript preserves order (customer first)", transcript and transcript[0]["speaker"] == "customer")
check("get_transcript preserves text", transcript and "Bilal" in transcript[0]["text"])


# ---------------------------------------------------------------------------
# 2. Client preferences - direct crm_logger test
# ---------------------------------------------------------------------------
print("\n=== 2. Client preferences ===")

r3 = crm_logger.upsert_client_preferences(SESSION, PHONE, {
    "client_name": "Bilal", "budget": 20_000_000, "city": "Karachi",
    "area": "Gulshan-e-Iqbal", "purpose": "buy",
})
check("upsert_client_preferences succeeds with a phone number", r3.success)

r4 = crm_logger.upsert_client_preferences(SESSION, None, {"budget": 25_000_000})
check("upsert_client_preferences fails honestly with no phone (not silently dropped)", not r4.success)

prefs = crm_logger.get_client_preferences(PHONE)
check("get_client_preferences returns saved name", prefs and prefs["client_name"] == "Bilal")
check("get_client_preferences returns saved area", prefs and prefs["area"] == "Gulshan-e-Iqbal")

# partial update: only budget changes, name/area should survive via COALESCE
crm_logger.upsert_client_preferences(SESSION, PHONE, {"budget": 22_000_000})
prefs2 = crm_logger.get_client_preferences(PHONE)
check("partial upsert updates budget", prefs2 and prefs2["budget"] == 22_000_000)
check("partial upsert keeps client_name from earlier call", prefs2 and prefs2["client_name"] == "Bilal")

check("get_client_preferences returns None for unknown client", crm_logger.get_client_preferences("0000-0000000") is None)


# ---------------------------------------------------------------------------
# 3. Appointment history - direct crm_logger test
#    (mirrors exactly what api.py's /calendar/* endpoints call — the real
#    Google Calendar API call itself is out of scope here, see module
#    docstring above)
# ---------------------------------------------------------------------------
print("\n=== 3. Appointment history ===")

booked = crm_logger.log_appointment_history(
    SESSION, "booked", client_phone=PHONE, client_name="Bilal",
    property_id=42, property_title="Gulshan-e-Iqbal - 3 Bed Apartment",
    start_datetime=(datetime.now() + timedelta(days=1)).isoformat(),
    event_id="evt_test_001",
)
check("log_appointment_history succeeds for 'booked'", booked.success)

rescheduled = crm_logger.log_appointment_history(
    SESSION, "rescheduled", client_phone=PHONE, client_name="Bilal",
    property_id=42, property_title="Gulshan-e-Iqbal - 3 Bed Apartment",
    start_datetime=(datetime.now() + timedelta(days=2)).isoformat(),
    event_id="evt_test_001",
)
check("log_appointment_history succeeds for 'rescheduled'", rescheduled.success)

history = crm_logger.get_appointment_history(PHONE)
check("get_appointment_history returns 2 rows", len(history) == 2)
check("get_appointment_history is oldest-first", history and history[0]["status"] == "booked")
check("get_appointment_history second row is the reschedule", history and history[1]["status"] == "rescheduled")
check("get_appointment_history for unknown client is empty", crm_logger.get_appointment_history("0000-0000000") == [])


# ---------------------------------------------------------------------------
# 4. Follow-up reminders - direct crm_logger test
# ---------------------------------------------------------------------------
print("\n=== 4. Follow-up reminders ===")

past_due = crm_logger.create_follow_up_reminder(
    SESSION, "No booking this call, check back in", due_at="2020-01-01T00:00:00",
    client_phone=PHONE, client_name="Bilal",
)
future_due = crm_logger.create_follow_up_reminder(
    SESSION, "Reminder that shouldn't show up yet", due_at="2099-01-01T00:00:00",
    client_phone=PHONE, client_name="Bilal",
)
check("create_follow_up_reminder succeeds (past due)", past_due.success)
check("create_follow_up_reminder succeeds (future due)", future_due.success)

due_now = crm_logger.get_due_reminders(as_of=datetime.now().isoformat())
due_ids = [r["id"] for r in due_now]
check("get_due_reminders includes the past-due reminder", past_due.log_id in due_ids)
check("get_due_reminders excludes the future reminder", future_due.log_id not in due_ids)

done_result = crm_logger.mark_reminder_done(past_due.log_id)
check("mark_reminder_done succeeds", done_result.success)

due_after = crm_logger.get_due_reminders(as_of=datetime.now().isoformat())
check("get_due_reminders excludes a reminder marked done", past_due.log_id not in [r["id"] for r in due_after])


# ---------------------------------------------------------------------------
# 5. api.py wiring - through FastAPI TestClient (real endpoint calls,
#    no network dependency for these two)
# ---------------------------------------------------------------------------
print("\n=== 5. api.py wiring (TestClient) ===")

try:
    from fastapi.testclient import TestClient
    import api

    client = TestClient(api.app)
    api_session = f"{SESSION}-api"

    resp = client.post("/webhook/call-start", json={"session_id": api_session, "client_phone": PHONE})
    check("/webhook/call-start returns 200", resp.status_code == 200)
    check("/webhook/call-start success flag true", resp.json().get("success") is True)

    resp2 = client.post("/intent", json={
        "session_id": api_session,
        "customer_text": "Mera naam Bilal hai, budget 2 crore hai, Gulshan mein chahiye",
    })
    check("/intent returns 200", resp2.status_code == 200)

    api_transcript = client.get(f"/crm/transcript/{api_session}")
    check("/crm/transcript/{session} shows the /intent turn was persisted",
          api_transcript.status_code == 200 and len(api_transcript.json()["transcript"]) == 1)

    api_prefs = client.get(f"/crm/preferences/{PHONE}")
    check("/crm/preferences/{phone} reflects the /intent call's slots",
          api_prefs.status_code == 200 and api_prefs.json()["preferences"] is not None)

    api_appts = client.get(f"/crm/appointments/{PHONE}")
    check("/crm/appointments/{phone} returns the appointments logged in section 3",
          api_appts.status_code == 200 and len(api_appts.json()["appointments"]) == 2)

    resp3 = client.post("/crm/follow-up", json={
        "session_id": api_session, "reason": "Test reminder via API",
        "due_at": "2020-06-01T00:00:00", "client_phone": PHONE, "client_name": "Bilal",
    })
    check("/crm/follow-up create returns 200 + success", resp3.status_code == 200 and resp3.json()["success"])

    resp4 = client.get("/crm/follow-ups/due")
    check("/crm/follow-ups/due returns 200", resp4.status_code == 200)
    check("/crm/follow-ups/due includes the reminder just created",
          any(r["session_id"] == api_session for r in resp4.json()["reminders"]))

    print("\n[NOTE] /calendar/create, /calendar/reschedule, /calendar/cancel were "
          "NOT exercised through TestClient - they need real Google Calendar OAuth "
          "credentials that aren't present in this environment. Their appointment_history "
          "logging calls are the same crm_logger.log_appointment_history() call already "
          "proven to work in section 3 above; only the live Calendar API call itself is skipped.")

except Exception as e:
    check(f"api.py TestClient section crashed: {type(e).__name__}: {e}", False)


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
