"""
Day 5 - Task 2: Graph Design

Assembles the LangGraph StateGraph from nodes.py's 10 nodes. Every routing
decision is a deterministic conditional edge (see nodes.py's module
docstring for why - graph routing is never left to an LLM's judgement in
this project).

    START --(no customer_text yet, first turn of the call)--> greeting --> END
    START --(customer_text present)--> intent_detection
    START --(empty customer_text on a LATER turn - dead air, not call start)--> silence --> END
    intent_detection --(explicit "talk to a human")--> escalation --> END
    intent_detection --(goodbye keywords)--> goodbye --> END
    intent_detection --(appointment_intent == book)--> booking
    intent_detection --(appointment_intent == reschedule)--> rescheduling
    intent_detection --(appointment_intent == cancel)--> cancellation
    intent_detection --(call_intent == seller_inquiry)--> seller --> END
    intent_detection --(looks like a factual/FAQ question)--> rag --> END
    intent_detection --(otherwise)--> recommendation --> END
    booking/rescheduling/cancellation --(succeeded)--> email --> END
    booking/rescheduling/cancellation --(real technical failure)--> escalation --> END
    booking/rescheduling/cancellation --(missing info / slot unavailable)--> END

This module is the ONLY conversation orchestrator in the project - the one
place AgentState/SessionStore/routing/tool-calling/guardrails live. It has
no knowledge of audio at all: run_turn() takes/returns plain text. The live
mic-to-speaker loop (Deepgram Live STT in, Fish Audio TTS out) lives in
live_voice_pipeline.py, which imports this module for run_turn() and
live_audio_io.py for the mic/speaker edges - graph.py itself is never
audio-aware, and there is exactly one live conversation loop in the
project, not one per orchestrator.
"""

import os
import re
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, START, END

from state import AgentState, SessionStore
from graph_logger import get_execution_trace
from speech_behaviors import SpeechBehaviorLayer
import nodes


# Native Urdu-script question words alongside the Roman-script ones - same
# reasoning as conversation_memory.py's _NAME_PATTERNS_URDU_SCRIPT: STT can
# hand back either script, and both are checked in one pass since re's \b
# doesn't reliably bound Arabic-script runs the way it does ASCII words.
_QUESTION_WORDS = re.compile(
    r"\b(kya|kaisa|kaisi|kaise|kab|kahan|kyun|kyu|kitna|kitni|kitne|konsa|konsi|kaun|"
    r"amenities|policy|maintenance|payment\s*plan|schools?|hospitals?)\b"
    r"|(کیا|کیسا|کیسی|کیسے|کب|کہاں|کیوں|کتنا|کتنی|کتنے|کونسا|کونسی|کون|"
    # native-script domain nouns, so a genuinely factual question phrased
    # without an explicit question word ("قریب کوئی اسکول ہے؟" - "is
    # there a school nearby?") still routes correctly without needing the
    # bare "?" fallback below at all
    r"اسکول|ہسپتال|سہولیات|پالیسی|دیکھ\s*بھال|مینٹیننس|ادائیگی)",
    re.IGNORECASE,
)

# Recommendation-continuation language ("a cheaper one?", "anything
# bigger?") - checked BEFORE the bare "?" fallback below, since these are
# a much stronger, more specific signal that this is a property-search
# refinement, not a factual lookup, and a bare question mark alone can't
# tell the two apart (Deepgram's smart_format adds real "?" characters to
# genuinely detected question intonation, so a "?" shows up on both kinds
# of turn equally).
_RECOMMENDATION_CONTINUATION_WORDS = re.compile(
    r"\b(sasti|sasta|cheaper|affordable|bara|bari|chota|choti|bigger|smaller)\b"
    r"|(سستی|سستا|کم\s*بجٹ|بڑا|بڑی|چھوٹا|چھوٹی)",
    re.IGNORECASE,
)


def _looks_like_factual_question(text: str) -> bool:
    """Heuristic split between 'answer a fact' (rag_node) and 'find me a
    property' (recommendation_node) - best-effort keyword matching, same
    honest-limitations spirit as appointment_intent.py's date parser: not
    perfect NLU, but deterministic and good enough for the common case.

    Confirmed live: "Us se sasti koi option hai?" (a cheaper option than
    that?) - a clear recommendation-continuation turn, not a factual
    lookup - misrouted to rag_node purely because it ended in a "?". A
    bare question mark is real signal (Deepgram's smart_format adds it
    for genuinely detected question intonation) but too weak ON ITS OWN,
    since both a factual question and a search refinement are commonly
    phrased as questions. Recommendation-continuation language now takes
    priority over a bare "?" when both are present."""
    if _RECOMMENDATION_CONTINUATION_WORDS.search(text):
        return False
    return bool(_QUESTION_WORDS.search(text)) or "?" in text


def _entry_router(state: AgentState) -> str:
    if state["customer_text"]:
        return "intent_detection"
    # Day 6 finding: this used to be `"greeting" if not customer_text else
    # ...` unconditionally - meaning ANY empty transcript (e.g. Deepgram
    # returning nothing for a few seconds of dead air mid-call) replayed
    # the call's opening greeting line as if the call had just started,
    # confirmed live in the evaluation suite's silent_caller scenarios.
    # turn_id is incremented in run_turn() BEFORE this router runs, so
    # turn_id==1 genuinely means "this is the first turn of the call" -
    # anything after that with empty text is dead air, not a fresh start.
    return "greeting" if state["turn_id"] <= 1 else "silence"


def _route_after_intent(state: AgentState) -> str:
    if nodes.detect_escalation_request(state["customer_text"]):
        return "escalation"
    if nodes.is_goodbye_turn(state):
        return "goodbye"

    appointment_intent = state["intent"].get("appointment_intent")
    if appointment_intent == "book":
        return "booking"
    if appointment_intent == "reschedule":
        return "rescheduling"
    if appointment_intent == "cancel":
        return "cancellation"

    if state["intent"].get("call_intent") == "seller_inquiry":
        return "seller"

    if _looks_like_factual_question(state["customer_text"]):
        return "rag"
    return "recommendation"


def _route_after_write_action(state: AgentState) -> str:
    last = state["tool_outputs"].get("last_write_action", {})
    if last.get("success"):
        return "email"
    if state.get("clarification_needed"):
        # missing info or an unavailable slot - stays in conversation, the
        # customer just needs to answer/pick again, not a real failure
        return END
    # a real technical failure (calendar/API error) - Day 1 ESCALATION RULES
    return "escalation"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("greeting", nodes.greeting_node)
    graph.add_node("silence", nodes.silence_node)
    graph.add_node("intent_detection", nodes.intent_detection_node)
    graph.add_node("rag", nodes.rag_node)
    graph.add_node("recommendation", nodes.recommendation_node)
    graph.add_node("seller", nodes.seller_node)
    graph.add_node("booking", nodes.booking_node)
    graph.add_node("rescheduling", nodes.rescheduling_node)
    graph.add_node("cancellation", nodes.cancellation_node)
    graph.add_node("email", nodes.email_node)
    graph.add_node("escalation", nodes.escalation_node)
    graph.add_node("goodbye", nodes.goodbye_node)

    graph.add_conditional_edges(START, _entry_router,
                                 {"greeting": "greeting", "silence": "silence", "intent_detection": "intent_detection"})
    graph.add_conditional_edges("intent_detection", _route_after_intent, {
        "escalation": "escalation", "goodbye": "goodbye", "booking": "booking",
        "rescheduling": "rescheduling", "cancellation": "cancellation",
        "seller": "seller", "rag": "rag", "recommendation": "recommendation",
    })
    graph.add_conditional_edges("booking", _route_after_write_action,
                                 {"email": "email", "escalation": "escalation", END: END})
    graph.add_conditional_edges("rescheduling", _route_after_write_action,
                                 {"email": "email", "escalation": "escalation", END: END})
    graph.add_conditional_edges("cancellation", _route_after_write_action,
                                 {"email": "email", "escalation": "escalation", END: END})

    graph.add_edge("greeting", END)
    graph.add_edge("silence", END)
    graph.add_edge("rag", END)
    graph.add_edge("recommendation", END)
    graph.add_edge("seller", END)
    graph.add_edge("email", END)
    graph.add_edge("escalation", END)
    graph.add_edge("goodbye", END)

    return graph.compile()


_compiled_graph = None


def _get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


_session_store = SessionStore()

# Day 3 Task 2 (speech_behaviors.py), applied centrally here rather than
# inside every node, so it can never be forgotten on one reply path and not
# another. Only wraps replies that came from an actual reasoning/tool step
# (rag/recommendation) - booking/reschedule/cancel/escalation/goodbye
# replies are already complete, deliberate confirmations and a "hmm, ek
# second..." in front of them would read as stalling, not natural.
_speech_layer = SpeechBehaviorLayer()
_WRAPPABLE_NODES = {"rag", "recommendation"}


def run_turn(session_id: str, customer_text: str = "", caller_id: Optional[str] = None) -> Tuple[str, List[dict]]:
    """Runs one turn through the compiled graph for session_id. Empty
    customer_text is a call-start/greeting invocation. Returns
    (agent_reply, node_trace) - node_trace is this turn's annotated
    execution trace from graph_logger (Task 5), ready to print or show in
    a UI. AgentState (budget, preferences, appointment status, history) is
    kept in SessionStore and persists across calls for the same session_id,
    including across an entire live voice session - see
    live_voice_pipeline.py, which calls this once per caller utterance
    under one fixed session_id.

    caller_id: the phone number a future telephony provider hands over out
    of band (e.g. Twilio's "From" field on every webhook for the call) -
    NOT wired to a real provider yet, this is the plumbing for when it is.
    Pass it on every turn (it's constant for the whole call, so re-setting
    it is harmless) and booking_node will never need to ask for a phone
    number verbally at all. If the customer explicitly states a DIFFERENT
    number later (e.g. calling from someone else's phone), that voice-
    parsed number still wins - conversation_memory.py's phone regex only
    overwrites user_profile.client_phone when it actually finds a new
    number in customer_text, so caller_id only ever acts as the starting
    default, never a hard override."""
    state = _session_store.get_or_create(session_id)
    if caller_id:
        state["caller_id"] = caller_id
        if not state["user_profile"].get("client_phone"):
            state["user_profile"]["client_phone"] = caller_id
    state["customer_text"] = customer_text
    state["turn_id"] = state.get("turn_id", 0) + 1

    result_state = _get_compiled_graph().invoke(state)

    _session_store.save(result_state)
    trace = get_execution_trace(session_id, result_state["turn_id"])

    reply = result_state.get("agent_reply", "")
    node_names = {row["node_name"] for row in trace}
    if reply and node_names & _WRAPPABLE_NODES:
        reply = _speech_layer.wrap_reply(reply, used_tool=True, is_reasoning_heavy=True)

    return reply, trace


def get_session_state(session_id: str) -> Optional[AgentState]:
    return _session_store._sessions.get(session_id)


def save_graph_diagram(path: Optional[str] = None) -> str:
    """Renders the compiled graph's structure to a PNG (via LangGraph's
    Mermaid renderer) - a visual of Task 2's routing table, not something
    generated from the execution traces."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "graph_diagram.png")
    path = os.path.abspath(path)
    png_bytes = _get_compiled_graph().get_graph().draw_mermaid_png()
    with open(path, "wb") as f:
        f.write(png_bytes)
    return path


if __name__ == "__main__":
    try:
        diagram_path = save_graph_diagram()
        print(f"Graph diagram saved to: {diagram_path}\n")
    except Exception as e:
        print(f"Could not render graph diagram (non-fatal, needs network access to mermaid.ink): {e}\n")

    sid = "graph-smoke-test"

    reply, trace = run_turn(sid, "")
    print("AGENT:", reply)

    reply, trace = run_turn(
        sid,
        "Assalam o Alaikum, mera naam Ahmed hai, budget 3 crore hai, DHA Phase 6 mein ghar chahiye.",
    )
    print("AGENT:", reply)
    print(f"\nTrace for this turn ({len(trace)} node(s)):")
    for row in trace:
        print(f"  {row['node_name']} ({row['duration_ms']}ms) - {row['annotation']}")

    print(
        "\nFor a live mic-to-speaker conversation through this same graph, run "
        "live_voice_pipeline.py instead (python live_voice_pipeline.py --session <id>)."
    )