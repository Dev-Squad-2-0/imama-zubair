"""
Week 7 - Day 5: Live Streaming Voice Pipeline (unified agent entry point)

    User speaks -> Microphone -> Deepgram Live STT (streaming)
        -> LangGraph unified agent (graph.run_turn)
        -> Fish Audio TTS -> Play audio -> wait for user to speak again

This module is I/O only. It owns none of the conversation logic - no
persona, no prompts, no tools, no routing. Every turn goes through exactly
one brain, graph.py's compiled LangGraph StateGraph:

    persona/system prompt (Day 1)      -> nodes.py's BASE_PROMPT, used by
                                           every LLM-calling node
    RAG / structured retrieval (Day 2) -> tools.py -> rag_pipeline.py /
                                           structured_retrieval.py
    LLM + memory + objection handling  -> llm_client.py, AgentState
    (Day 3)                               (conversation_history, decline_count),
                                           objection_handler.py, all via nodes.py
    appointments / calendar / email /  -> tools.py -> calendar_integration.py /
    CRM (Day 4)                           email_automation.py / crm_logger.py
    LangGraph orchestration, state,    -> graph.py / state.py / nodes.py
    routing, tracing (Day 5)

There is no second agent implementation here and no branch that picks
between conversation_agent.py and graph.py - this file always calls
graph.run_turn(), full stop.

Two new edges are added on top of that, both hardware/network boundaries
graph.py itself has no knowledge of:
  1. live audio in  -> transcript   (live_audio_io.listen_for_utterance,
     Deepgram's streaming/websocket API)
  2. agent_reply     -> speaker out (live_audio_io.play_audio_bytes, Fish
     Audio TTS via voice_pipeline.py, played instead of saved to disk)

AgentState (conversation history, user profile, budget/city/area/bedrooms,
intent, tool outputs, appointment status) lives in graph.py's SessionStore
under one fixed session_id for the whole call, so it persists turn to turn
for the entire live session - if the caller says "Mera budget 3 crore hai"
and two turns later "DHA mein options hain?", intent_detection_node's
slots_from_text() has already folded the budget into property_preferences
and it's still there when recommendation_node runs.

Barge-in (interrupting the agent mid-reply) is NOT implemented yet - this
is turn-based: the mic is closed while the agent is speaking and reopens
right after, so there's no self-hearing/echo loop, at the cost of not
being able to cut the agent off mid-sentence.

Requires (not needed by the rest of Day 5) - matches the deepgram-sdk==3.7.7
already pinned for voice_pipeline.py's prerecorded STT, no SDK upgrade needed:
    pip install pygame
Deepgram's Microphone helper additionally needs PyAudio, which itself needs
PortAudio installed at the OS level:
    macOS:   brew install portaudio
    Ubuntu:  sudo apt-get install portaudio19-dev
    Windows: PyAudio installs pre-built, nothing extra needed

Run:
    cd Day5/src
    python live_voice_pipeline.py                 # live mic conversation loop
    python live_voice_pipeline.py --session my-id  # use a specific session id
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import graph  # the ONE orchestrator: LangGraph StateGraph, AgentState, SessionStore
import live_audio_io as io  # I/O only: mic -> Deepgram Live STT, speaker <- Fish Audio TTS
import voice_pipeline as vp  # reused: TTS warmup + sentence splitting/emotion tagging
from nodes import GOODBYE_KEYWORDS  # same list nodes.py's own is_goodbye_turn() uses -
# this file used to keep its own separate, Roman-only goodbye regex here,
# which could (and did start to) drift out of sync with nodes.py's list as
# each got updated independently. Now there is exactly one goodbye keyword
# list in the whole project.


def speak_reply(reply_text: str):
    """Splits agent_reply into sentences and plays each as it's synthesized -
    reuses voice_pipeline.py's existing sentence splitting/emotion tagging
    as-is, just plays live instead of saving to disk."""
    for sentence in vp._split_into_sentences(reply_text):
        tagged = vp._apply_emotion_tag(sentence)
        print(f"AGENT: {sentence}")
        try:
            audio_bytes, _ = vp.tts_stream_audio(tagged)
        except RuntimeError as e:
            print(f"  [live_voice_pipeline] TTS failed for this sentence, skipping: {e}")
            continue
        io.play_audio_bytes(audio_bytes)


def run_live_session(session_id: str = "live-caller"):
    """The full loop: greet -> (listen -> graph.run_turn -> speak) forever,
    until the caller says goodbye, a turn produces no reply, or the process
    is interrupted. session_id is fixed for the whole call, which is what
    lets graph.py's SessionStore carry AgentState across every turn."""
    print(f"Starting live session '{session_id}'. Press Ctrl+C to end the call.\n")

    vp.warmup_tts()

    reply, _trace = graph.run_turn(session_id, "")  # empty text -> greeting_node
    if reply:
        speak_reply(reply)

    try:
        while True:
            transcript = io.listen_for_utterance()
            if transcript is None:
                continue

            print(f"USER: {transcript}")

            reply, trace = graph.run_turn(session_id, transcript)
            if reply:
                speak_reply(reply)

            if any(kw in transcript.lower() for kw in GOODBYE_KEYWORDS) or not reply:
                print("\nCall ended.")
                break

    except KeyboardInterrupt:
        print("\nCall interrupted by user.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live mic-to-speaker session through the unified LangGraph agent.")
    parser.add_argument("--session", default="live-caller", help="Session id to use/resume.")
    args = parser.parse_args()

    try:
        run_live_session(args.session)
    except RuntimeError as e:
        print(f"Live pipeline failed to start: {e}")
        print(
            "Check that DEEPGRAM_API_KEY / BASE_URL / API_KEY / FISH_AUDIO_API_KEY are "
            "set in your .env, and that PortAudio is installed (needed by PyAudio, "
            "which Deepgram's Microphone helper uses)."
        )
        raise SystemExit(1)