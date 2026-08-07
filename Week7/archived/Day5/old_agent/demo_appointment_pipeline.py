"""
Day 4 - Sample end-to-end run.

Proves the full stack is actually wired together, nothing mocked:

    1 real audio file
        -> Deepgram STT               (voice_pipeline.py, Day 3)
        -> real streaming LLM reply   (conversation_agent.py, Day 3)
        -> real Fish Audio TTS        (voice_pipeline.py, Day 3)
    then, continuing the same call with real customer text turns:
        -> real property matching + RAG grounding   (Day 2 / Day 3)
        -> real appointment booking                 (appointment_management.py, Day 4)
           - real Google Calendar event created
           - real email sent to the employee

Turn 1 is the only turn that goes through actual audio + STT (that's the
part Task 1 of Day 3 already proved works end to end). Turns 2+ are
text, exactly like a transcript would look after STT — conversation_agent.py
treats both identically (run_turn() always takes already-transcribed text,
see its docstring), so this isn't a different code path, just a shorter
one to run since we don't have pre-recorded audio for "book me an
appointment for tomorrow" in sample_audio/. Every LLM reply and every TTS
call in every turn below is real.

Run from src/:
    python3 demo_appointment_pipeline.py
"""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conversation_memory import ConversationMemory
from speech_behaviors import SpeechBehaviorLayer
from voice_pipeline import load_audio_file, stt_transcribe, SAMPLE_AUDIO_DIR
from conversation_agent import run_turn

DEMO_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "generated_audio", "fish_audio", "demo_appointment_pipeline"
)


def _find_sample_audio_file() -> str | None:
    if not os.path.isdir(SAMPLE_AUDIO_DIR):
        return None
    files = sorted(
        f for f in glob.glob(os.path.join(SAMPLE_AUDIO_DIR, "*"))
        if os.path.splitext(f)[1].lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac")
    )
    return files[0] if files else None


def run_demo():
    memory = ConversationMemory()
    behaviors = SpeechBehaviorLayer(seed=11)

    print("=" * 80)
    print("STEP 1: Real audio file -> Deepgram STT")
    print("=" * 80)

    audio_path = _find_sample_audio_file()
    if not audio_path:
        print(f"No sample audio found in {SAMPLE_AUDIO_DIR}. "
              f"Falling back to typed text for turn 1 instead of a real audio file — "
              f"everything downstream (LLM, TTS, booking) still runs for real.")
        turn_1_text = "Assalam o alaikum, mujhe ghar chahiye Lahore mein, DHA Phase 6 mein."
    else:
        print(f"Audio file: {audio_path}")
        audio_bytes, mimetype = load_audio_file(audio_path)
        turn_1_text, stt_ms = stt_transcribe(audio_bytes, mimetype=mimetype)
        print(f"Transcript (Deepgram, real): {turn_1_text!r}  [stt: {stt_ms}ms]")

    print("\n" + "=" * 80)
    print("STEP 2: Full conversation, real streaming LLM + real Fish Audio TTS")
    print("=" * 80)

    # Turn 1 uses whatever the real audio file actually said. Turns 2-4 are
    # scripted text so the call has a concrete client name/phone/property/
    # date-time to book against by the end — same shape a real call would
    # reach after a few turns, just condensed so this demo finishes quickly.
    turns = [
        turn_1_text,
        "Budget 3 crore hai, DHA Phase 6 mein.",
        "Mera naam Ahmed hai, mera number 0300-1234567 hai.",
        "Theek hai, kal shaam 5 baje appointment book kar dein.",
    ]

    for i, customer_text in enumerate(turns, start=1):
        print(f"\n--- Turn {i} ---")
        print(f"CUSTOMER: {customer_text}")
        spoken, report = run_turn(customer_text, memory, behaviors, output_dir=DEMO_OUTPUT_DIR)
        print(f"AGENT: {spoken}")
        if report:
            print(f"  [latency to first audio: {report.total_first_audio_ms}ms, "
                  f"{'within' if report.under_budget else 'OVER'} 2000ms budget]")
            if report.audio_file_paths:
                print(f"  [TTS audio saved: {report.audio_file_paths}]")

    print("\n" + "=" * 80)
    print("STEP 3: Appointment state after the call (Day 4, Task 3)")
    print("=" * 80)

    pending = memory.slots.pending_appointment
    if pending:
        print(f"Status: {pending['status']}")
        print(f"Event ID (Google Calendar): {pending['event_id']}")
        print(f"Property: {pending['property_title']}")
        print(f"Time: {pending['start_datetime']}")
        print(f"Employee: {pending['employee_name']} ({pending.get('employee_email')})")
        print("\nIf event_id is a real Calendar event ID (not None), check the calendar "
              "and the employee's inbox — both should show this appointment now.")
    else:
        print("No appointment was booked this call (check the AGENT replies above for why — "
              "most likely a missing detail was flagged instead of the booking going through).")


if __name__ == "__main__":
    run_demo()
