"""
Day 1-5 unified agent - TEXT front end (no microphone).

This file is now a thin front end over graph.py's compiled LangGraph brain
(state.py's AgentState/SessionStore, nodes.py's 10 nodes, graph.py's
routing) - the exact same orchestrator live_voice_pipeline.py drives with
a mic. There is exactly ONE brain in this project (graph.run_turn); this
module and live_voice_pipeline.py are its two front ends:

    conversation_agent.py   -> text in, text out (CLI / scripted turns) -
                                no audio deps at all, used for Day 6 test
                                suites, prompt-injection tests, quick manual
                                back-and-forth, and anywhere you want to
                                exercise Day 1-5 logic without a mic/speaker.
    live_voice_pipeline.py  -> mic in, speaker out (Deepgram Live STT +
                                Fish Audio TTS via live_audio_io.py) - the
                                only place audio hardware is touched.

Both call graph.run_turn(session_id, customer_text) for every turn, so
persona/system prompt (Day 1), RAG/structured retrieval (Day 2), memory/
objection handling (Day 3), appointments/Calendar/email/CRM (Day 4), and
LangGraph routing/tracing (Day 5) behave identically from either front end.
Nothing conversation-logic-shaped lives in this file - no persona, no
prompts, no tools, no routing, no ConversationMemory/SpeechBehaviorLayer
instantiation. If a reply looks wrong, the fix belongs in nodes.py/graph.py,
not here.

Run:
    python conversation_agent.py                    # interactive text chat
    python conversation_agent.py --session my-id     # resume/use a specific session
    python conversation_agent.py --script turns.txt  # replay one utterance per line
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import graph  # the ONE orchestrator: LangGraph StateGraph, AgentState, SessionStore

_GOODBYE_WORDS_HINT = ("bye", "khuda hafiz", "allah hafiz", "good bye")


def run_text_turn(session_id: str, customer_text: str = "") -> tuple[str, list]:
    """One turn, plain text in -> plain text out. Direct pass-through to
    graph.run_turn() - kept as its own function (rather than callers using
    graph.run_turn directly) so Day 6 test/eval code has one stable text-only
    entry point to import, independent of which module owns the graph."""
    return graph.run_turn(session_id, customer_text)


def run_scripted_conversation(turns: list[str], session_id: str = "text-session",
                               verbose: bool = True) -> list[dict]:
    """Feeds a list of customer utterances through run_text_turn() in order,
    under one session_id so AgentState (budget, city, appointment status,
    decline_count, ...) persists turn to turn exactly like a real call.
    Returns a list of {customer_text, agent_reply, trace} dicts - handy for
    Day 6's 40+ scripted test conversations, prompt-injection checks, and
    any other automated eval that needs the full transcript + node trace
    back rather than just printed output.

    An empty-text greeting turn is run first automatically, same as a real
    call/live session always starts with graph.run_turn(session_id, "").
    """
    results = []

    greeting_reply, greeting_trace = run_text_turn(session_id, "")
    if verbose and greeting_reply:
        print(f"AGENT: {greeting_reply}")
    results.append({"customer_text": "", "agent_reply": greeting_reply, "trace": greeting_trace})

    for text in turns:
        if verbose:
            print(f"CUSTOMER: {text}")
        reply, trace = run_text_turn(session_id, text)
        if verbose:
            print(f"AGENT: {reply}")
            if trace:
                node_path = " -> ".join(row["node_name"] for row in trace)
                print(f"  [nodes: {node_path}]")
        results.append({"customer_text": text, "agent_reply": reply, "trace": trace})

        if not reply or any(w in text.lower() for w in _GOODBYE_WORDS_HINT):
            break

    return results


def run_text_conversation(session_id: str = "text-caller"):
    """Interactive back-and-forth over stdin/stdout - the no-mic equivalent
    of live_voice_pipeline.run_live_session(), same brain, same session
    continuity, just typed input instead of a microphone and printed
    replies instead of TTS playback. Exactly what Day 6 manual testing
    (and prompt-injection probing) wants: fast, no audio hardware, no
    Deepgram/Fish Audio API keys required.

    Type an empty line or Ctrl+C/Ctrl+D to end the call.
    """
    print(f"Starting text session '{session_id}'. Empty line or Ctrl+C to end the call.\n")

    reply, _trace = run_text_turn(session_id, "")
    if reply:
        print(f"AGENT: {reply}\n")

    try:
        while True:
            try:
                customer_text = input("YOU: ").strip()
            except EOFError:
                print("\nCall ended.")
                break

            if not customer_text:
                print("\nCall ended.")
                break

            reply, trace = run_text_turn(session_id, customer_text)
            print(f"AGENT: {reply}")
            if trace:
                node_path = " -> ".join(row["node_name"] for row in trace)
                print(f"  [nodes: {node_path}]")
            print()

            if not reply:
                print("Call ended (empty reply).")
                break

    except KeyboardInterrupt:
        print("\nCall interrupted by user.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Text-only (no mic) front end for the Day 1-5 LangGraph voice agent."
    )
    parser.add_argument("--session", default="text-caller", help="Session id to use/resume.")
    parser.add_argument(
        "--script", default=None,
        help="Path to a text file with one customer utterance per line; replays it "
             "non-interactively instead of prompting for input (useful for Day 6 test scripts).",
    )
    args = parser.parse_args()

    if args.script:
        with open(args.script, encoding="utf-8") as f:
            scripted_turns = [line.strip() for line in f if line.strip()]
        run_scripted_conversation(scripted_turns, session_id=args.session)
    else:
        run_text_conversation(args.session)
