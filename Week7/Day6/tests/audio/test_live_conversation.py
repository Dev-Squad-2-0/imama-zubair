"""Interactive live voice-agent test harness.

This is intentionally NOT a unittest/pytest test because it requires a human
speaking into the microphone. It launches the production live voice pipeline:

    Mic -> Deepgram Live STT -> LangGraph -> Fish Audio -> speaker
                          ^                    |
                          +------ barge-in ----+

Run from project root:
    python tests/audio/test_live_conversation.py

Caller ID is taken from TEST_CALLER_ID in .env. It is treated as telephony
metadata and stored in AgentState/CRM; the agent never asks you for it.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import live_voice_pipeline


if __name__ == "__main__":
    caller_id = os.getenv("TEST_CALLER_ID")
    session_id = f"live-test-{time.strftime('%Y%m%d-%H%M%S')}"

    print("\nInteractive live voice-agent test")
    print("- Speak naturally in Urdu / English / UrduLish.")
    print("- Speak while the agent is talking to test barge-in.")
    print("- Use headphones/headset for reliable interruption detection.")
    print("- Say Allah Hafiz / goodbye to end the session.\n")

    live_voice_pipeline.run_live_session(
        session_id=session_id,
        caller_id=caller_id,
        enable_barge_in=True,
    )
