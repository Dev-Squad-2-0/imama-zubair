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
import time
import re
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, START, END

from state import AgentState, SessionStore
from graph_logger import get_execution_trace
import monitoring
import crm_logger
import nodes
from security_guard import is_security_sensitive_request


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
    r"\b(sasti|sasta|cheaper|cheap|affordable|bara|bari|chota|choti|"
    r"bigger|smaller|thora\s+kam|thori\s+kam|kam\s+price|aur\s+option|"
    r"another\s+option|same\s+area|us\s+se\s+sasti|is\s+se\s+sasti)\b"
    r"|(سستی|سستا|کم\s*بجٹ|کم\s*قیمت|اور\s*آپشن|بڑا|بڑی|چھوٹا|چھوٹی)",
    re.IGNORECASE,
)

# Strong signals that the caller is still talking about the real-estate task.
# If none of these are present and the utterance looks conversational, route
# to small_talk instead of defaulting every unknown sentence to a buyer search.
_DOMAIN_WORDS = re.compile(
    r"\b(property|ghar|house|apartment|flat|plot|shop|office|warehouse|"
    r"rent|lease|buy|purchase|sell|investment|invest|budget|crore|lakh|"
    r"marla|kanal|bedroom|bathroom|dha|bahria|gulberg|johar|phase|"
    r"appointment|booking|book|reschedule|cancel|visit|price|available|availability)\b"
    r"|(پراپرٹی|گھر|اپارٹمنٹ|فلیٹ|پلاٹ|دکان|دفتر|گودام|رینٹ|کرایہ|"
    r"خرید|بیچ|انویسٹمنٹ|بجٹ|کروڑ|لاکھ|مرلہ|کنال|بیڈروم|"
    r"اپوائنٹمنٹ|بکنگ|بک|ریس|کینسل|وزٹ|قیمت|دستیاب)",
    re.IGNORECASE,
)

_SMALL_TALK_HINTS = re.compile(
    r"\b(how are you|how r you|kaise ho|kaisay ho|kya haal|what'?s up|"
    r"weather|garmi|sardi|barish|joke|funny|football|cricket|movie|"
    r"your name|aap ka naam|tumhara naam|thank you|thanks|shukriya|"
    r"nice|acha laga|hello again|busy ho)\b"
    r"|(کیسے ہو|کیا حال|موسم|گرمی|سردی|بارش|لطیفہ|فٹبال|کرکٹ|"
    r"آپ کا نام|تمہارا نام|شکریہ|وعلیکم السلام|السلام علیکم|ہیلو)",
    re.IGNORECASE,
)


def _looks_like_small_talk(text: str) -> bool:
    """Conservative small-talk split.

    Explicit domain/appointment language always wins. Otherwise a known
    conversational cue, or a short utterance with no domain signal, can be
    handled naturally instead of being forced into recommendation_node.
    """
    cleaned = (text or "").strip()
    if not cleaned or _DOMAIN_WORDS.search(cleaned):
        return False

    # "Us se sasti koi option hai?", "kuch cheaper?", "thora kam wala?"
    # are contextual recommendation refinements, not small talk. This must
    # run before the short-utterance fallback below.
    if _RECOMMENDATION_CONTINUATION_WORDS.search(cleaned):
        return False

    if _SMALL_TALK_HINTS.search(cleaned):
        return True

    # Short unknown remarks are much more likely to be conversational noise
    # / small talk than a complete property search. Longer unknown turns
    # stay on the old path so we do not over-route real requests.
    words = re.findall(r"[\w\u0600-\u06FF]+", cleaned)
    return 0 < len(words) <= 8




def _looks_like_recommendation_followup(state: AgentState) -> bool:
    """A short comparative turn can rely entirely on previous recommendations.

    Example:
        Turn 1: "3 crore, DHA Phase 6 mein ghar chahiye"
        Turn 2: "Us se sasti koi option hai?"

    The second turn contains no explicit property noun, but it is only meaningful
    because the prior turn showed properties. Treat it as recommendation refinement
    when prior recommendation state exists.
    """
    text = state.get("customer_text", "")
    if not _RECOMMENDATION_CONTINUATION_WORDS.search(text):
        return False

    tool_outputs = state.get("tool_outputs") or {}
    prefs = state.get("property_preferences") or {}

    return bool(
        tool_outputs.get("last_recommendations")
        or prefs.get("last_shown_property_ids")
        or prefs.get("last_shown_min_price")
        or prefs.get("budget")
        or prefs.get("area")
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
    # Security-sensitive caller text is intercepted BEFORE any LLM-facing node.
    # This prevents prompt extraction from reaching small_talk/RAG/recommendation
    # with the system prompt attached.
    if is_security_sensitive_request(state["customer_text"]):
        return "security_guard"

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

    if _looks_like_recommendation_followup(state):
        return "recommendation"

    if _looks_like_factual_question(state["customer_text"]):
        return "rag"

    if _looks_like_small_talk(state["customer_text"]):
        return "small_talk"

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
    graph.add_node("security_guard", nodes.security_guard_node)
    graph.add_node("small_talk", nodes.small_talk_node)
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
        "security_guard": "security_guard",
        "seller": "seller", "rag": "rag", "small_talk": "small_talk",
        "recommendation": "recommendation",
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
    graph.add_edge("security_guard", END)
    graph.add_edge("small_talk", END)
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

# Replies are spoken exactly as produced by the selected node/LLM.
# The live graph does not prepend hardcoded filler or fake waiting phrases.


def _log_transcript_nonfatal(session_id: str, speaker: str, text: str) -> None:
    """Persist one CRM transcript row without ever taking down the call.

    crm_logger already returns a CRMLogResult instead of raising. Checking
    that result here makes a DB/path/schema problem visible in the live
    terminal instead of silently producing an empty call_transcripts table.
    """
    if not (text or "").strip():
        return

    result = crm_logger.log_transcript_turn(session_id, speaker, text.strip())
    if not result.success:
        print(
            f"[crm] failed to log {speaker} transcript for {session_id}: "
            f"{result.error}"
        )


def run_turn(session_id: str, customer_text: str = "", caller_id: Optional[str] = None) -> Tuple[str, List[dict]]:
    """Runs one turn through the compiled graph for session_id.

    CRM transcript persistence is centralized here because graph.run_turn()
    is the common path used by the live Deepgram voice pipeline. Every
    non-empty customer transcript is written before graph execution, and
    every final agent reply is written after speech-behavior wrapping so the
    database reflects the same wording that Fish Audio is asked to speak.

    Empty customer_text is the call-start/greeting invocation, so it does
    not create a fake blank customer row; the greeting itself is still
    logged as an agent transcript.
    """
    turn_started = time.perf_counter()
    state = _session_store.get_or_create(session_id)

    if caller_id:
        state["caller_id"] = caller_id
        if not state["user_profile"].get("client_phone"):
            state["user_profile"]["client_phone"] = caller_id

    state["customer_text"] = customer_text
    state["turn_id"] = state.get("turn_id", 0) + 1

    # Persist exactly what Deepgram handed to the graph. Do this before
    # invoking LangGraph so a downstream LLM/tool failure does not erase the
    # fact that the caller actually said this turn.
    _log_transcript_nonfatal(session_id, "customer", customer_text)

    result_state = _get_compiled_graph().invoke(state)
    _session_store.save(result_state)

    # Persist the telephony caller number as the stable CRM identity. The
    # caller never has to speak their own phone number; caller_id comes from
    # the phone provider and run_turn() has already copied it into
    # user_profile.client_phone. Every later turn refreshes newly learned
    # profile/property preferences under that same number.
    stored_phone = result_state.get("user_profile", {}).get("client_phone")
    if stored_phone:
        crm_slots = {
            "client_name": result_state.get("user_profile", {}).get("client_name"),
            **result_state.get("property_preferences", {}),
        }

        pref_result = crm_logger.upsert_client_preferences(
            session_id,
            stored_phone,
            crm_slots,
        )
        if not pref_result.success:
            print(
                f"[crm] failed to upsert preferences for {stored_phone}: "
                f"{pref_result.error}"
            )

        if result_state.get("turn_id") == 1:
            event_result = crm_logger.log_event(
                session_id,
                "call_started",
                {"client_phone": stored_phone},
            )
            if not event_result.success:
                print(
                    f"[crm] failed to log call_started for {session_id}: "
                    f"{event_result.error}"
                )

    trace = get_execution_trace(session_id, result_state["turn_id"])

    reply = result_state.get("agent_reply", "")
    node_names = {row["node_name"] for row in trace}

    # Log the FINAL response after the speech wrapper. This is the actual
    # text returned to live_voice_pipeline.py and therefore the wording sent
    # to Fish Audio TTS.
    _log_transcript_nonfatal(session_id, "agent", reply)
    monitoring.record_graph_turn(session_id, (time.perf_counter() - turn_started) * 1000, success=True)

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