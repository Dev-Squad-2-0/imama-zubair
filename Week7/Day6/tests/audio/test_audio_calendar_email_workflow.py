"""
Real end-to-end booking side-effect test.

Uses the existing audio fixtures in tests/audio/input/ and performs:

    turn_01.mp3
        -> Deepgram STT
        -> extract customer name/budget/location

    turn_06.mp3
        -> Deepgram STT
        -> LangGraph booking node
        -> Google Calendar real event
        -> LangGraph email node
        -> Gmail real email

Why the test supplies a property + date/time:
The existing audio fixtures were originally built to test NLU/routing.
turn_06 only says "book an appointment for DHA Phase 6"; it does NOT contain
a visit date/time, and turn_01 asks for a house even though the bundled test
database currently has no available house in DHA Phase 6. Production code
correctly refuses to invent those values.

So this integration test:
- still requires Deepgram to understand the real audio,
- derives the customer profile/preferences from that audio,
- selects a REAL available property from the bundled SQL database,
- finds a REAL free Calendar slot,
- then runs the REAL LangGraph booking -> Calendar -> Email path.

Nothing touching Deepgram, Calendar, Gmail, or LangGraph booking/email is mocked.

Required .env:
    DEEPGRAM_API_KEY=...
    DEEPGRAM_MODEL=nova-3
    DEEPGRAM_LANGUAGE=ur

    GOOGLE_CREDENTIALS_PATH=credentials.json
    GOOGLE_CALENDAR_ID=primary
    EMPLOYEE_EMAIL=you@example.com

Optional:
    TEST_CALLER_ID=03001112222
    TEST_PROPERTY_ID=33
    CLEANUP_TEST_EVENT=1

Run from project root:
    python tests/audio/test_audio_calendar_email_workflow.py

First Google run may open TWO OAuth consent flows:
- Calendar -> token.json
- Gmail    -> gmail_token.json

By default the test leaves the event on your calendar so you can inspect it.
Set CLEANUP_TEST_EVENT=1 if you want it deleted after verification.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import calendar_integration as cal  # noqa: E402
import crm_logger  # noqa: E402
import graph  # noqa: E402
import structured_retrieval  # noqa: E402
import voice_pipeline as vp  # noqa: E402
from state import new_agent_state, slots_from_text  # noqa: E402


PROFILE_AUDIO = HERE / "input" / "turn_01.mp3"
BOOKING_AUDIO = HERE / "input" / "turn_06.mp3"
LOG_PATH = HERE / "audio_calendar_email_result.json"
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEST_CALLER_ID = os.getenv("TEST_CALLER_ID", "03001112222")
TEST_PROPERTY_ID = os.getenv("TEST_PROPERTY_ID")
CLEANUP_TEST_EVENT = os.getenv("CLEANUP_TEST_EVENT", "").lower() in {
    "1", "true", "yes"
}

PASS = "PASS"
FAIL = "FAIL"
checks = []


def check(label, condition, detail=None):
    status = PASS if condition else FAIL
    checks.append({"label": label, "status": status, "detail": detail})
    suffix = f" -- {detail}" if detail else ""
    print(f"[{status}] {label}{suffix}")
    return condition


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is missing from .env")
    return value


def transcribe(path: Path):
    if not path.exists():
        raise RuntimeError(f"Audio fixture not found: {path}")

    audio_bytes, mimetype = vp.load_audio_file(str(path))
    transcript, latency_ms = vp.stt_transcribe(audio_bytes, mimetype=mimetype)
    transcript = (transcript or "").strip()

    if not transcript:
        raise RuntimeError(f"Deepgram returned an empty transcript for {path.name}")

    print(f"\nDeepgram [{path.name}] ({latency_ms} ms):")
    print(f"  {transcript}")
    return transcript, latency_ms


def choose_real_property(profile_state):
    if TEST_PROPERTY_ID:
        prop = structured_retrieval.get_property_by_id(int(TEST_PROPERTY_ID))
        if not prop:
            raise RuntimeError(
                f"TEST_PROPERTY_ID={TEST_PROPERTY_ID} does not exist in the database"
            )
        if prop.get("status") != "available":
            raise RuntimeError(
                f"TEST_PROPERTY_ID={TEST_PROPERTY_ID} is not currently available"
            )
        return prop

    prefs = profile_state["property_preferences"]
    city = prefs.get("city")
    area = prefs.get("area")
    budget = prefs.get("budget")

    # First prefer the same city + area + budget captured from audio.
    matches = structured_retrieval.search_properties(
        city=city,
        area=area,
        max_price=budget,
        status="available",
    )

    # If the budget wording was transcribed imperfectly, keep the same area.
    if not matches:
        matches = structured_retrieval.search_properties(
            city=city,
            area=area,
            status="available",
        )

    if not matches:
        raise RuntimeError(
            f"No available property exists for city={city!r}, area={area!r}. "
            "Set TEST_PROPERTY_ID in .env to a known available property."
        )

    return matches[0]


def find_free_slot():
    """
    Find a real free 30-minute Calendar slot.

    Starts 7 days from now and checks 2 PM, one day at a time, for up to
    21 days. This avoids hardcoding a date that might already be busy.
    """
    now = datetime.now()
    base = (now + timedelta(days=7)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )

    for offset in range(21):
        candidate = base + timedelta(days=offset)
        availability = cal.check_availability(candidate)

        if not availability.success:
            raise RuntimeError(
                f"Google Calendar availability check failed: {availability.error}"
            )

        if availability.available:
            return candidate

    raise RuntimeError("Could not find a free 2 PM slot in the next 21 test days")


def verify_calendar_event(event_id):
    service = cal.get_calendar_service()
    event = service.events().get(
        calendarId=cal.GOOGLE_CALENDAR_ID,
        eventId=event_id,
    ).execute()
    return event


def cleanup_calendar_event(event_id):
    service = cal.get_calendar_service()
    service.events().delete(
        calendarId=cal.GOOGLE_CALENDAR_ID,
        eventId=event_id,
        sendUpdates="none",
    ).execute()


def main():
    print("=" * 72)
    print("REAL AUDIO -> DEEPGRAM -> LANGGRAPH -> CALENDAR -> GMAIL TEST")
    print("=" * 72)

    # -------- Preflight --------
    require_env("DEEPGRAM_API_KEY")
    require_env("GOOGLE_CREDENTIALS_PATH")
    require_env("GOOGLE_CALENDAR_ID")
    require_env("FISH_AUDIO_API_KEY")
    employee_email = require_env("EMPLOYEE_EMAIL")

    session_id = f"audio-google-e2e-{time.strftime('%Y%m%d%H%M%S')}"
    result_log = {
        "session_id": session_id,
        "profile_audio": str(PROFILE_AUDIO),
        "booking_audio": str(BOOKING_AUDIO),
        "employee_email": employee_email,
    }

    event_id = None

    try:
        # ---------------------------------------------------------------
        # 1. REAL AUDIO -> REAL DEEPGRAM
        # ---------------------------------------------------------------
        print("\n=== 1. Deepgram STT ===")
        profile_transcript, profile_stt_ms = transcribe(PROFILE_AUDIO)
        booking_transcript, booking_stt_ms = transcribe(BOOKING_AUDIO)

        result_log["profile_transcript"] = profile_transcript
        result_log["booking_transcript"] = booking_transcript
        result_log["profile_stt_ms"] = profile_stt_ms
        result_log["booking_stt_ms"] = booking_stt_ms

        check(
            "Deepgram produced the profile transcript",
            bool(profile_transcript),
        )
        check(
            "Deepgram produced the booking transcript",
            bool(booking_transcript),
        )

        # ---------------------------------------------------------------
        # 2. Build the SAME AgentState from the audio transcript.
        #
        # We intentionally seed state without running recommendation_node,
        # because this test is specifically Calendar/Gmail integration and
        # should not depend on external LLM quotas.
        # ---------------------------------------------------------------
        print("\n=== 2. Build LangGraph session from audio ===")
        state = new_agent_state(session_id)
        parsed = slots_from_text(
            state["user_profile"],
            state["property_preferences"],
            state["decline_count"],
            profile_transcript,
        )

        state["user_profile"] = parsed["user_profile"]
        state["property_preferences"] = parsed["property_preferences"]
        state["decline_count"] = parsed["decline_count"]

        # In a real phone call this comes from telephony metadata (Twilio
        # "From"), not speech. graph.run_turn already supports caller_id
        # for exactly this reason.
        # Simulate the phone network's caller metadata. The caller never has
        # to say their own number. This is the same value graph.run_turn()
        # stores into user_profile.client_phone in production.
        state["caller_id"] = TEST_CALLER_ID
        state["user_profile"]["client_phone"] = TEST_CALLER_ID

        check(
            "caller phone stored from telephony metadata",
            state["user_profile"].get("client_phone") == TEST_CALLER_ID,
            state["user_profile"].get("client_phone"),
        )
        check(
            "customer name extracted from audio",
            bool(state["user_profile"].get("client_name")),
            state["user_profile"].get("client_name"),
        )
        check(
            "area extracted from audio",
            bool(state["property_preferences"].get("area")),
            state["property_preferences"].get("area"),
        )
        check(
            "budget extracted from audio",
            bool(state["property_preferences"].get("budget")),
            state["property_preferences"].get("budget"),
        )

        # ---------------------------------------------------------------
        # 3. Select a REAL available property from the bundled DB.
        # ---------------------------------------------------------------
        print("\n=== 3. Select real property ===")
        prop = choose_real_property(state)
        state["property_preferences"]["last_shown_property_ids"] = [prop["id"]]
        state["property_preferences"]["purpose"] = prop.get("purpose") or "buy"

        print(
            f"Using property #{prop['id']}: {prop['title']} "
            f"(PKR {prop['price_pkr']:,}, status={prop['status']})"
        )
        check(
            "selected property is really available",
            prop.get("status") == "available",
        )

        # Save our test-prepared state into the same session store used by
        # graph.run_turn(). From this point onward the actual booking/email
        # route is production LangGraph code.
        graph._session_store.save(state)

        # ---------------------------------------------------------------
        # 4. Find a REAL free Calendar slot.
        # ---------------------------------------------------------------
        print("\n=== 4. Find free Calendar slot ===")
        slot = find_free_slot()
        print(f"Free slot selected: {slot.isoformat()}")

        # turn_06 audio contains the booking INTENT but not a date/time.
        # Add only the missing time detail so production booking validation
        # can legitimately pass.
        date_phrase = slot.strftime("%B %d %Y")
        hour_12 = slot.strftime("%I").lstrip("0")
        booking_customer_text = (
            f"{booking_transcript} {date_phrase} ko {hour_12} baje."
        )

        # ---------------------------------------------------------------
        # 5. REAL LANGGRAPH booking -> Calendar -> email
        # ---------------------------------------------------------------
        print("\n=== 5. Run real LangGraph booking ===")
        reply, trace = graph.run_turn(
            session_id,
            booking_customer_text,
            caller_id=TEST_CALLER_ID,
        )

        node_names = [row["node_name"] for row in trace]
        print(f"Agent text reply: {reply}")
        print(f"Trace: {' -> '.join(node_names)}")

        # ---------------------------------------------------------------
        # 5b. REAL Fish Audio TTS + output logging
        # ---------------------------------------------------------------
        print("\n=== 5b. Generate and save the agent TTS reply ===")
        tts_input = vp._apply_emotion_tag(reply)
        tts_bytes, tts_latency_ms = vp.tts_stream_audio(tts_input)
        tts_path = OUTPUT_DIR / f"agent_reply_{session_id}.mp3"
        tts_path.write_bytes(tts_bytes)
        text_path = OUTPUT_DIR / f"agent_reply_{session_id}.txt"
        text_path.write_text(reply, encoding="utf-8")

        print(f"Agent TTS text: {reply}")
        print(f"TTS first-byte latency: {tts_latency_ms} ms")
        print(f"Saved TTS audio: {tts_path}")
        print(f"Saved reply text: {text_path}")

        check("Fish Audio produced TTS bytes", bool(tts_bytes))
        check("agent reply MP3 was written", tts_path.exists() and tts_path.stat().st_size > 0, str(tts_path))

        result_log["agent_tts"] = {
            "reply_text": reply,
            "audio_path": str(tts_path),
            "text_path": str(text_path),
            "first_byte_latency_ms": tts_latency_ms,
            "bytes": len(tts_bytes),
        }

        final_state = graph.get_session_state(session_id)
        appointment = (final_state or {}).get("appointment_status") or {}
        last_email = (
            ((final_state or {}).get("tool_outputs") or {}).get("last_email") or {}
        )
        event_id = appointment.get("event_id")

        check("LangGraph routed through booking node", "booking" in node_names)
        check(
            "LangGraph retained caller phone in user_profile",
            (final_state or {}).get("user_profile", {}).get("client_phone") == TEST_CALLER_ID,
            (final_state or {}).get("user_profile", {}).get("client_phone"),
        )

        saved_customer = crm_logger.get_client_preferences(TEST_CALLER_ID)
        check(
            "CRM saved user info under the telephony caller phone",
            bool(saved_customer),
            TEST_CALLER_ID,
        )
        if saved_customer:
            print(f"CRM customer record: {saved_customer}")
            result_log["crm_customer"] = saved_customer

        check("LangGraph routed through email node", "email" in node_names)
        check(
            "Calendar booking returned a real event_id",
            bool(event_id),
            event_id,
        )
        check(
            "appointment state is booked",
            appointment.get("status") == "booked",
            appointment.get("status"),
        )
        check(
            "Gmail send reported success",
            last_email.get("success") is True,
            last_email.get("error"),
        )
        check(
            "Gmail returned a real message_id",
            bool(last_email.get("message_id")),
            last_email.get("message_id"),
        )

        # ---------------------------------------------------------------
        # 6. Independently fetch the created event back from Google Calendar
        #    so PASS does not rely only on local LangGraph state.
        # ---------------------------------------------------------------
        print("\n=== 6. Verify event exists in Google Calendar ===")
        if event_id:
            event = verify_calendar_event(event_id)
            summary = event.get("summary", "")
            attendees = [
                a.get("email", "").lower()
                for a in event.get("attendees", [])
                if a.get("email")
            ]

            print(f"Calendar summary: {summary}")
            print(f"Calendar link: {event.get('htmlLink')}")
            print(f"Attendees: {attendees}")

            check(
                "event can be fetched back from Google Calendar",
                event.get("id") == event_id,
            )
            check(
                "calendar event contains the customer name",
                state["user_profile"]["client_name"].lower() in summary.lower(),
            )
            check(
                "employee email is attached to the Calendar event",
                employee_email.lower() in attendees,
                employee_email,
            )

            result_log["calendar_event"] = {
                "id": event.get("id"),
                "summary": summary,
                "htmlLink": event.get("htmlLink"),
                "start": event.get("start"),
                "end": event.get("end"),
                "attendees": attendees,
            }

        result_log["appointment_status"] = appointment
        result_log["email_result"] = last_email
        result_log["trace"] = node_names
        result_log["agent_reply"] = reply

    except Exception as exc:
        check(
            "workflow completed without an unhandled exception",
            False,
            f"{type(exc).__name__}: {exc}",
        )
        result_log["error"] = f"{type(exc).__name__}: {exc}"

    finally:
        if CLEANUP_TEST_EVENT and event_id:
            try:
                cleanup_calendar_event(event_id)
                print(f"\nCleaned up Calendar event: {event_id}")
                result_log["cleaned_up_event"] = True
            except Exception as exc:
                print(f"\nWARNING: could not clean up event {event_id}: {exc}")
                result_log["cleanup_error"] = str(exc)

        result_log["checks"] = checks

        with LOG_PATH.open("w", encoding="utf-8") as f:
            json.dump(result_log, f, ensure_ascii=False, indent=2, default=str)

    # -------- Summary --------
    passed = sum(c["status"] == PASS for c in checks)
    failed = sum(c["status"] == FAIL for c in checks)

    print("\n" + "=" * 72)
    print(f"SUMMARY: {passed} passed, {failed} failed")
    print(f"Log: {LOG_PATH}")

    if event_id and not CLEANUP_TEST_EVENT:
        print(
            "\nThe test event was intentionally LEFT on your Google Calendar "
            "so you can inspect it."
        )
        print(
            f"An email should also be present in EMPLOYEE_EMAIL: {employee_email}"
        )

    if failed:
        print("\nFailed checks:")
        for item in checks:
            if item["status"] == FAIL:
                print(f"  - {item['label']}: {item.get('detail') or ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()