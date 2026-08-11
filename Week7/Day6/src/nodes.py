"""
Day 5 - Task 2 node implementations (+ Task 4 validation gates).

Graph ROUTING (which node runs next) stays fully deterministic throughout -
driven by Day 4's proven keyword classifiers (call_intent.py,
appointment_intent.py, objection_handler.py), never by an LLM's own
judgement about what to do. This preserves Day 4's core safety property
("the LLM never gets to invent a booking confirmation") and is what makes
Task 4's guardrails ("never book an unavailable slot", "never recommend an
unavailable property", "ask instead of guessing") structurally enforceable
rather than merely encouraged by a prompt.

The one exception, and the one place this project does real LLM
tool-calling, is rag_node: choosing between semantic search
(rag_search_tool) and an exact structured lookup (property_lookup_tool) for
a factual question is safe to leave to the model (both are read-only), and
is exactly what Day 5 Task 3 means by "tool calling."

Every node is a plain `def node(state: AgentState) -> dict` returning a
PARTIAL state update (LangGraph merges it in) and is wrapped with
@traced_node (Task 5) right where it's defined.
"""

import difflib
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_core.utils.function_calling import convert_to_openai_tool

from state import AgentState, slots_from_text
from conversation_memory import extract_client_name
from graph_logger import traced_node
import llm_client
from call_intent import classify_call_intent, has_explicit_buyer_signal
from appointment_intent import (
    detect_appointment_intent,
    parse_appointment_datetime,
    parse_reschedule_datetime,
    resolve_stateful_appointment_intent,
)
from objection_handler import detect_objection, build_strategy
import structured_retrieval
import crm_logger
import monitoring
from tools import (
    search_property_tool, check_availability_tool, book_calendar_tool,
    reschedule_calendar_tool, cancel_calendar_tool, email_tool, crm_log_tool,
    rag_search_tool, property_lookup_tool,
)

# ---------- Prompt registry ----------
# All LLM-facing conversational instructions live in ONE Markdown file:
# prompts/system_prompt.md. prompt_loader.py extracts BASE + the current node
# section, so nodes.py stays focused on software behavior.
from prompt_loader import base_prompt, node_prompt
from security_guard import security_reason, safe_security_reply

BASE_PROMPT = base_prompt()


# ---------- shared helpers ----------

def _say(state: AgentState, reply: str) -> List[Dict[str, str]]:
    return state["conversation_history"] + [{"speaker": "agent", "text": reply}]


def _recent_history(state: AgentState, n: int = 8) -> List[Dict[str, str]]:
    """Last n turns of conversation_history EXCLUDING the current customer
    turn (that's passed separately as the LLM call's user_prompt, see
    recommendation_node/rag_node) - caps how much context each call carries
    so a long call doesn't compound both token cost and latency turn after
    turn. By the time this runs, intent_detection_node has already appended
    the current customer turn as the LAST entry, hence the [:-1]."""
    history = state["conversation_history"]
    prior = history[:-1] if history and history[-1].get("speaker") == "customer" else history
    return prior[-n:]


_PROPERTY_ID_PATTERN = re.compile(
    r"(?:property|پراپرٹی)\s*(?:(?:number|no\.?|#|نمبر)\s*)?([0-9۰-۹]+)",
    re.IGNORECASE,
)
_PROPERTY_ID_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _extract_mentioned_property_id(customer_text: str) -> Optional[int]:
    m = _PROPERTY_ID_PATTERN.search(customer_text or "")
    if not m:
        return None
    return int(m.group(1).translate(_PROPERTY_ID_DIGITS))


def _write_action_update(state: AgentState, kind: str, success: bool, agent_reply: str,
                          **extra: Any) -> Dict[str, Any]:
    """Every booking/reschedule/cancel code path returns through this.

    ``tool_outputs`` is MERGED rather than replaced so a pending booking
    draft (name/property/date gathered over several caller turns) survives
    every clarification turn while ``last_write_action`` is still always
    present for graph.py's post-write routing.
    """
    explicit_tool_outputs = extra.pop("tool_outputs", None)
    merged_tool_outputs = dict(state["tool_outputs"])
    if explicit_tool_outputs:
        merged_tool_outputs.update(explicit_tool_outputs)
    # Set this LAST so a caller-supplied tool_outputs dict containing an old
    # last_write_action can never overwrite the action from THIS node run.
    merged_tool_outputs["last_write_action"] = {"kind": kind, "success": success}

    return {
        "agent_reply": agent_reply,
        "conversation_history": _say(state, agent_reply),
        "tool_outputs": merged_tool_outputs,
        **extra,
    }


def _restore_active_appointment_from_crm(state: AgentState) -> Optional[Dict[str, Any]]:
    """Return the caller's latest non-cancelled appointment from CRM.

    SessionStore is intentionally in-memory, while Google Calendar/CRM are
    persistent. Without this recovery step, restarting the live demo loses
    ``appointment_status`` and a returning caller cannot reschedule an event
    that still exists on Calendar.
    """
    current = state.get("appointment_status") or {}
    if current.get("event_id") and current.get("status") != "cancelled":
        return current

    phone = (state.get("user_profile") or {}).get("client_phone") or state.get("caller_id")
    if not phone:
        return None

    history = crm_logger.get_appointment_history(phone)
    if not history:
        return None

    cancelled_event_ids = set()
    for row in reversed(history):
        event_id = row.get("event_id")
        if not event_id:
            continue
        status = (row.get("status") or "").lower()
        if status == "cancelled":
            cancelled_event_ids.add(event_id)
            continue
        if event_id in cancelled_event_ids:
            continue
        if status in {"booked", "rescheduled"}:
            return {
                "event_id": event_id,
                "property_title": row.get("property_title"),
                "property_id": row.get("property_id"),
                "start_datetime": row.get("start_datetime"),
                "employee_name": "RealEstate Hub Agent",
                "employee_email": None,
                "status": status,
            }
    return None


# ---------- 1. Greeting ----------

_GREETING_LINE = (
    "Assalam-o-Alaikum customer! RealEstate Hub se baat ho rahi hai. "
    "Main aap ki kis tarah madad kar sakta hoon?"
)


@traced_node("greeting", annotate=lambda i, o: "opening line sent")
def greeting_node(state: AgentState) -> Dict[str, Any]:
    """Fires only on a call-start invocation (empty customer_text, see
    graph.py's entry router) - the agent's opening line, before there's
    anything from the customer to route on."""
    return {"agent_reply": _GREETING_LINE, "conversation_history": _say(state, _GREETING_LINE)}


@traced_node("silence", annotate=lambda i, o: "dead air prompt sent")
def silence_node(state: AgentState) -> Dict[str, Any]:
    """Day 6 finding: empty customer_text mid-call (dead air, a dropped
    STT result) used to route straight back to greeting_node, replaying
    the call's opening line as if it had just started - confirmed via the
    evaluation suite's silent_caller scenarios. graph.py's _entry_router
    now sends empty-text turns here instead, UNLESS it's genuinely turn 1
    of the call. Deterministic, no LLM call - there's no real customer
    text to reason about, and a templated "are you there?" prompt is
    exactly as good as anything an LLM would produce here, for free."""
    reply = "Hmm... aap wahan hain? Agar sun rahe hain toh please bata dijiye, main sun raha hoon."
    return {"agent_reply": reply, "conversation_history": _say(state, reply)}


# ---------- 2. Intent Detection ----------

GOODBYE_KEYWORDS = [
    "shukriya", "thank you", "thanks", "bye", "khuda hafiz", "allah hafiz",
    "theek hai bas", "bas itna hi", "koi masla nahi",
    # Call-ending phrases - observed live in STT: callers say "call end",
    # "call band", or "end kar" when they want to hang up, and these are
    # not generic enough to be confused with domain content.
    "call end", "end the call", "call band", "band kar", "end kar",
    "band karo", "khatam kar", "phone rakh",
    # native Urdu script - see conversation_memory.py's _NAME_PATTERNS_URDU_SCRIPT
    # comment for why this is a real second pattern set, not a transliteration step
    "شکریہ", "خدا حافظ", "اللہ حافظ", "بس اتنا ہی", "ٹھیک ہے بس",
    "کال اینڈ", "کال بند", "بند کر", "ختم کر", "فون رکھ",
]

_ESCALATION_KEYWORDS = [
    "human se baat", "insaan se baat", "kisi insaan se", "real agent",
    "actual agent", "speak to a human", "speak to someone", "talk to a person",
    "manager se baat", "supervisor se baat", "representative se baat",
    "connect me to a human", "talk to a human",
    # native Urdu script
    "انسان سے بات", "کسی انسان سے", "منیجر سے بات", "سپروائزر سے بات",
    "ہیومن سے بات",  # transliterated loanword, see call_intent.py's _RENTAL_KEYWORDS comment
]


def detect_escalation_request(customer_text: str) -> bool:
    """Day 1 ESCALATION RULES: 'The customer explicitly asks for a human' -
    same deterministic keyword-classifier pattern as objection_handler.py/
    call_intent.py, checked by graph.py's router before anything else so an
    explicit request is honored 'immediately without resistance' regardless
    of whatever else this turn's text also contains."""
    lowered = customer_text.lower()
    return any(kw in lowered for kw in _ESCALATION_KEYWORDS)


def is_goodbye_turn(state: AgentState) -> bool:
    """Closing language only - checked by graph.py's router, not a node
    itself.

    Previously also returned True whenever should_stop_pushing(decline_count)
    was true (decline_count >= 2). That's wrong: nothing ever resets
    decline_count, so once a customer declined two property SUGGESTIONS,
    every subsequent turn for the rest of the call - a factual question, a
    booking request, anything - got silently routed to goodbye before the
    graph even looked at what they said (confirmed live: turns 4/6/7 in a
    session all got mis-routed to goodbye off one decline_count>=2 set on
    turn 3). system_prompt.md's actual guardrail is "do not continue
    pushing A SALE" - i.e. stop suggesting new properties, not end the
    call. That's now handled in recommendation_node's system prompt
    instead (see _recommendation_system_prompt), which is where a
    guardrail about sales pushiness belongs - it should change HOW
    recommendation_node behaves, not hijack routing for the whole rest of
    the conversation."""
    lowered = state["customer_text"].lower()
    return any(kw in lowered for kw in GOODBYE_KEYWORDS)


def _annotate_intent(_inp, out):
    intent = out.get("intent", {})
    return f"call_intent={intent.get('call_intent')}, appointment_intent={intent.get('appointment_intent')}"


_STICKY_CALL_INTENTS = {"seller_inquiry", "rental_inquiry", "commercial_inquiry", "investment_inquiry"}

_NAME_CONFIRM_YES = {
    "yes", "yeah", "yep", "correct", "right", "ji", "jee", "haan", "han", "bilkul",
    "جی", "ہاں", "بالکل", "صحیح", "درست",
}
_NAME_CONFIRM_NO = {
    "no", "nope", "nahi", "nahin", "galat", "wrong",
    "نہیں", "غلط",
}


def _simple_confirmation(text: str) -> Optional[bool]:
    """Return True/False only for short, unambiguous confirmation replies."""
    normalized = re.sub(r"[^\w\u0600-\u06FF]+", " ", (text or "").lower()).strip()
    if not normalized:
        return None
    words = normalized.split()
    if len(words) > 4:
        return None
    if any(word in _NAME_CONFIRM_NO for word in words):
        return False
    if any(word in _NAME_CONFIRM_YES for word in words):
        return True
    return None


@traced_node("intent_detection", annotate=_annotate_intent)
def intent_detection_node(state: AgentState) -> Dict[str, Any]:
    """Classifies this turn (Day 4's keyword classifiers, not an LLM call -
    see module docstring) and updates user_profile/property_preferences by
    reusing conversation_memory.py's proven slot parsers via
    state.slots_from_text() - no re-implementation of that extraction
    logic."""
    text = state["customer_text"]
    previous_missing = list(state.get("missing_fields") or [])
    pending_name = (state.get("tool_outputs") or {}).get("pending_name_confirmation")

    updates = slots_from_text(
        state["user_profile"],
        state["property_preferences"],
        state["decline_count"],
        text,
        expected_fields=previous_missing,
    )

    # Context-aware name capture. ``conversation_memory`` auto-saves strong
    # explicit/bare-in-name-context results. Here we handle the deliberately
    # uncertain middle ground by confirming once instead of discarding the
    # candidate or silently writing a bad ASR guess to CRM.
    updated_tool_outputs = dict(state.get("tool_outputs") or {})

    if pending_name:
        confirmation = _simple_confirmation(text)
        if confirmation is True:
            profile = dict(updates["user_profile"])
            profile["client_name"] = pending_name.get("candidate")
            updates["user_profile"] = profile
            updated_tool_outputs.pop("pending_name_confirmation", None)
        elif confirmation is False:
            updated_tool_outputs.pop("pending_name_confirmation", None)
        else:
            parsed = extract_client_name(text, expect_name=True)
            if parsed.name and parsed.confidence >= 0.85:
                profile = dict(updates["user_profile"])
                profile["client_name"] = parsed.name
                updates["user_profile"] = profile
                updated_tool_outputs.pop("pending_name_confirmation", None)
            elif parsed.name and parsed.confidence >= 0.55:
                updated_tool_outputs["pending_name_confirmation"] = {
                    "candidate": parsed.name,
                    "confidence": parsed.confidence,
                    "source": parsed.source,
                }
    elif (
        "client_name" in previous_missing
        and not updates["user_profile"].get("client_name")
    ):
        parsed = extract_client_name(text, expect_name=True)
        if parsed.name and parsed.confidence >= 0.85:
            profile = dict(updates["user_profile"])
            profile["client_name"] = parsed.name
            updates["user_profile"] = profile
        elif parsed.name and parsed.confidence >= 0.55:
            updated_tool_outputs["pending_name_confirmation"] = {
                "candidate": parsed.name,
                "confidence": parsed.confidence,
                "source": parsed.source,
            }

    # Appointment intent is STATEFUL, not a per-utterance label.
    #
    # A real booking is normally a multi-turn slot-filling flow:
    #   caller: "appointment book kar dein"       -> book
    #   agent:  asks for name/property/date/time
    #   caller: "Ali"                              -> no booking keyword
    #   caller: "5 baje"                           -> no booking keyword
    #
    # Re-running the keyword detector on each of those follow-up turns used
    # to overwrite ``book`` with None, which kicked the graph back into
    # recommendation/RAG instead of continuing through booking_node.
    #
    # Keep a pending ``book`` intent sticky until a real calendar booking
    # succeeds. Explicit appointment actions (cancel/reschedule/book) still
    # win immediately, so the caller can change course naturally.
    # Recover the latest active appointment for returning callers before
    # classifying this turn. This allows a fresh live session to reschedule
    # an appointment that was booked during an earlier call.
    had_appointment_in_state = bool(state.get("appointment_status"))
    restored_appointment = _restore_active_appointment_from_crm(state)
    if restored_appointment and not had_appointment_in_state:
        state = {**state, "appointment_status": restored_appointment}

    detected_appointment_intent = detect_appointment_intent(
        text, has_existing_appointment=bool(state.get("appointment_status"))
    )
    prev_appointment_intent = state["intent"].get("appointment_intent")
    last_write = (state.get("tool_outputs") or {}).get("last_write_action") or {}

    # Never use an old/restored appointment_status to end a newly-started
    # booking flow. Stay in the active flow until THAT flow writes
    # successfully to Calendar.
    appointment_intent = resolve_stateful_appointment_intent(
        detected_appointment_intent,
        prev_appointment_intent,
        last_write,
    )

    new_call_intent = classify_call_intent(text)
    prev_call_intent = state["intent"].get("call_intent")
    # Day 6 finding: call_intent used to be recomputed from THIS turn's
    # text alone every time, nothing carried forward - a seller who said
    # "book a valuation visit for tomorrow" on turn 2 (no selling-related
    # words in that sentence at all) silently flipped back to the generic
    # buyer_inquiry default, which then made booking_node treat them as a
    # buyer needing a real recommended property_id - the exact bug
    # seller_node/booking_node's seller support was just built to fix,
    # one turn later. Same shape of bug would hit rental/commercial/
    # investment customers the same way. Once one of these more specific
    # categories is known, a later turn that doesn't repeat its keywords
    # shouldn't silently downgrade it back to the default - but a later
    # turn that DOES carry a new specific signal (e.g. they clarify it's
    # actually a rental, not a sale) still correctly overrides it, since
    # this only kicks in when new_call_intent came back as the generic
    # fallback, never when it found a real signal of its own.
    if (
        new_call_intent == "buyer_inquiry"
        and prev_call_intent in _STICKY_CALL_INTENTS
        and not has_explicit_buyer_signal(text)
    ):
        call_intent = prev_call_intent
    else:
        call_intent = new_call_intent

    intent = {
        "call_intent": call_intent,
        "appointment_intent": appointment_intent,
        "objection": detect_objection(text),
    }

    result = {
        **updates,
        "conversation_history": state["conversation_history"] + [{"speaker": "customer", "text": text}],
        "intent": intent,
        "tool_outputs": updated_tool_outputs,
    }
    if restored_appointment and not had_appointment_in_state:
        result["appointment_status"] = restored_appointment
    return result




# ---------- 2a. Deterministic security guard ----------

@traced_node("security_guard", annotate=lambda i, o: "security-sensitive request blocked")
def security_guard_node(state: AgentState) -> Dict[str, Any]:
    """Handle prompt injection/private-data/tool-bypass requests without an LLM.

    This node deliberately never receives BASE_PROMPT and never calls a model.
    Therefore a prompt-extraction attack cannot succeed by convincing the model
    to echo the very prompt that contains the guardrail.
    """
    text = state.get("customer_text", "")
    reason = security_reason(text) or "security_sensitive_request"
    reply = safe_security_reply(text)

    try:
        crm_log_tool.invoke({
            "session_id": state["session_id"],
            "event_type": "security_request_blocked",
            "payload": {"reason": reason},
            "status": "blocked",
        })
    except Exception:
        # Security refusal must still work if CRM logging is unavailable.
        pass

    return {
        "agent_reply": reply,
        "conversation_history": _say(state, reply),
        "clarification_needed": False,
        "missing_fields": [],
    }


# ---------- 2b. Harmless small talk / slightly off-topic turns ----------

_SMALL_TALK_SYSTEM_PROMPT = node_prompt("SMALL_TALK", include_base=False)


@traced_node("small_talk", annotate=lambda i, o: "brief natural small-talk response")
def small_talk_node(state: AgentState) -> Dict[str, Any]:
    try:
        reply = llm_client.generate_reply(
            _SMALL_TALK_SYSTEM_PROMPT,
            state["customer_text"],
            history=_recent_history(state),
        )
        if not reply or not reply.strip():
            raise RuntimeError("empty small-talk response")
    except RuntimeError:
        # Natural deterministic fallback that does not pretend to have
        # personal experiences and does not use a stock tool-wait phrase.
        reply = (
            "Ji, samajh gaya. Waise property side par aap kis cheez mein "
            "help chahte hain — buy, rent, investment ya appointment?"
        )

    return {
        "agent_reply": reply.strip(),
        "conversation_history": _say(state, reply.strip()),
    }


# ---------- 3. RAG (the one node with real LLM tool-calling) ----------

_RAG_SYSTEM_PROMPT = node_prompt("RAG")

_RAG_TOOLS = [rag_search_tool, property_lookup_tool]
_RAG_TOOL_SCHEMAS = [convert_to_openai_tool(t) for t in _RAG_TOOLS]
_RAG_TOOLS_BY_NAME = {t.name: t for t in _RAG_TOOLS}


def _execute_rag_tool(name: str, args: Dict[str, Any]) -> Any:
    tool_fn = _RAG_TOOLS_BY_NAME.get(name)
    if tool_fn is None:
        return {"error": f"unknown tool {name!r}"}
    return tool_fn.invoke(args)


@traced_node("rag", annotate=lambda i, o: "answered via RAG/structured tool-calling")
def rag_node(state: AgentState) -> Dict[str, Any]:
    """Factual/FAQ questions. The model decides between semantic search and
    an exact structured lookup and must answer only from what the tool(s)
    return (never invents property facts) - same grounding guarantee Day
    4's rag_pipeline.generate_answer already enforced for plain RAG, now
    with real tool choice."""
    pid = _extract_mentioned_property_id(state["customer_text"])
    hint = f" (the customer may be referring to property id {pid})" if pid else ""
    rag_observation = {"hit_count": None}

    def execute_and_measure(name: str, args: Dict[str, Any]) -> Any:
        result = _execute_rag_tool(name, args)
        if name == "rag_search_tool" and isinstance(result, list):
            rag_observation["hit_count"] = len(result)
        elif name == "property_lookup_tool" and isinstance(result, dict):
            rag_observation["hit_count"] = 1 if result.get("found") else 0
        return result

    try:
        reply = llm_client.generate_with_tools(
            _RAG_SYSTEM_PROMPT, state["customer_text"] + hint, _RAG_TOOL_SCHEMAS, execute_and_measure,
            history=_recent_history(state),
        )
    except RuntimeError as e:
        reply = "Maazrat sir, is waqt yeh maloomat nikalne mein masla ho raha hai, thori dair baad dobara poochein."
    if rag_observation["hit_count"] is not None:
        monitoring.record_rag_result(state["session_id"], rag_observation["hit_count"])
    return {"agent_reply": reply, "conversation_history": _say(state, reply)}


# ---------- 4a. Seller inquiry (Day 6: no recommendation makes sense here - a
# customer offering to LIST their own property doesn't want company
# inventory recommended back to them, which is what recommendation_node
# would otherwise do by default. Deterministic, no LLM call: this is a
# short, fixed intake-and-handoff exchange, not a reasoning-heavy turn -
# every additional LLM call this session has cost 8-20s in practice, not
# worth paying that here for something a template says just as well.) ----------

@traced_node("seller", annotate=lambda i, o: "seller lead logged")
def seller_node(state: AgentState) -> Dict[str, Any]:
    """Acknowledges a seller lead, captures whatever conversation_memory.py
    already parsed this turn (name/phone/area/property_type - the same
    slots buyer flows use, reused here since they mean roughly the same
    thing for "property being sold" as "property being sought"), logs a
    CRM seller_lead event so a human agent can follow up and actually
    evaluate/list the property (valuing and listing a property is outside
    what a phone agent should decide on its own), and does NOT route into
    recommendation_node."""
    profile = state["user_profile"]
    prefs = state["property_preferences"]

    crm_log_tool.invoke({
        "session_id": state["session_id"], "event_type": "seller_lead",
        "payload": {
            "client_name": profile.get("client_name"), "client_phone": profile.get("client_phone"),
            "city": prefs.get("city"), "area": prefs.get("area"),
            "property_type": prefs.get("property_type"), "raw_text": state["customer_text"],
        },
    })

    name_part = f"{profile['client_name']} ji, " if profile.get("client_name") else ""
    if profile.get("client_phone"):
        reply = (f"Ji {name_part}bohot shukriya aap ki property RealEstate Hub ke saath list karne "
                 f"ke liye. Hamari team aap ko is number par contact karegi: {profile['client_phone']}, "
                 f"property ki details aur valuation discuss karne ke liye.")
    else:
        reply = (f"Ji {name_part}bohot shukriya, hum aap ki property list karne mein madad kar sakte "
                 f"hain. Iske liye hamari team ko aap ka naam aur contact number chahiye hoga, taake "
                 f"woh aap se rabta kar ke property ki details aur valuation discuss kar sakein.")

    return {"agent_reply": reply, "conversation_history": _say(state, reply)}


# ---------- 4b. Recommendation (LLM-chosen search args, validated against real data) ----------

#
# Day 2/4's design had search_property_tool called deterministically here,
# fed straight from conversation_memory.py's regex-parsed slots. That meant
# every area/city name customers might say had to exist in a hardcoded
# Python alias dict (conversation_memory.py's area_aliases) - which drifted
# out of sync with the real dataset (confirmed live: "Johar Town" and "DHA
# Phase 2" existed in the actual properties table but not in that dict, in
# EITHER script), and needed a parallel Urdu-script keyword list maintained
# by hand for every area, forever.
#
# This node now gives the LLM search_property_tool itself as a callable
# tool (the same generate_with_tools() pattern rag_node already uses to
# choose between rag_search_tool/property_lookup_tool) instead of a plain
# generate_reply() call - reusing the existing call, not adding a new one.
# The model's tool-call arguments ARE the extracted entities. Read-only
# search is safe to leave to the model for the same reason rag_node's tool
# choice is (nodes.py's module docstring). What's NOT safe is trusting an
# LLM-extracted city/area/property_type string outright - search_properties()
# filters with a plain SQL `WHERE city = ?` (exact match, case-sensitive),
# so a slightly-off value doesn't error, it just silently returns nothing.
# _execute_search_property_tool validates against
# structured_retrieval.get_distinct_cities()/get_distinct_areas()/
# get_distinct_property_types() (real data, not a hardcoded list) before
# ever calling the real tool, and corrects to the DB's exact canonical
# spelling on a match. On no match, the customer is told the value isn't
# recognized and asked to confirm - never silently dropped or guessed
# (Task 4: "ask clarification instead of guessing").
#
# conversation_memory.py's regex-based slot parsing is NOT removed - it
# still runs every turn in intent_detection_node (booking_node's required-
# field checks depend on it, and it's the fallback here if both LLM
# providers are down).

_RECOMMENDATION_TOOLS = [search_property_tool]
_RECOMMENDATION_TOOL_SCHEMAS = [convert_to_openai_tool(t) for t in _RECOMMENDATION_TOOLS]


def _validate_categorical(value: Optional[str], valid_values: List[str]):
    """Returns (corrected_value, unrecognized_original). Exact match, then
    case-insensitive exact match, then a fuzzy pass for STT noise/spelling
    drift (e.g. "Johar Twon"). On no match at all, returns (None, value) -
    the original is preserved so the reply can tell the customer exactly
    what wasn't recognized, rather than silently dropping it."""
    if not value:
        return None, None
    if value in valid_values:
        return value, None
    lower_map = {v.lower(): v for v in valid_values}
    if value.lower() in lower_map:
        return lower_map[value.lower()], None
    close = difflib.get_close_matches(value, valid_values, n=1, cutoff=0.6)
    if close:
        return close[0], None
    return None, value


# property_type is deterministically extracted and OVERRIDES whatever the
# LLM's tool call passed - confirmed live, twice: prompting the model to
# extract property_type (_recommendation_system_prompt's explicit mapping
# instructions) was not reliable enough on its own. A customer saying
# "اپارٹمنٹ چاہیے، گودام نہیں" (apartment please, NOT a warehouse) still
# got warehouses recommended, meaning property_type was never actually
# passed to the tool despite the instruction. Every other categorical
# field (city/area) is LLM-extracted then validated; this one is
# extracted deterministically and validated the same way, because getting
# it wrong shows the customer a property type they explicitly excluded,
# not just a slightly-off search - closer to a Task 4 guardrail than a
# nice-to-have.
_PROPERTY_TYPE_KEYWORDS = {
    "apartment": ["apartment", "flat", "اپارٹمنٹ", "فلیٹ"],
    "house": ["house", "ghar", "گھر"],
    "warehouse": ["warehouse", "godown", "گودام"],
    "office": ["office", "دفتر", "آفس"],
    "plot": ["plot", "پلاٹ"],
    "shop": ["shop", "dukan", "دکان"],
}
_NEGATION_WORDS = ["نہیں", "نہ", "nahi", "nahin", "nhi", "not", "no"]


def _detect_property_type(text: str) -> Optional[str]:
    """Returns the first NON-negated property-type mention, in text order
    - "گودام نہیں" (not a warehouse) is correctly skipped as an exclusion,
    not returned as the answer, by checking a short window right after
    each match for a negation word."""
    lowered = text.lower()
    candidates = []  # (property_type, position, is_negated)
    for ptype, keywords in _PROPERTY_TYPE_KEYWORDS.items():
        for kw in keywords:
            # ASCII property words need token boundaries: a plain
            # ``find("house")`` also matches the tail of ``warehouse`` and
            # can manufacture a positive house preference when the caller
            # actually said ``not warehouse``. Arabic-script phrases are
            # safe with literal matching because they do not have that
            # English compound-word overlap.
            if kw.isascii():
                matches = list(re.finditer(rf"(?<!\w){re.escape(kw)}(?!\w)", lowered))
                positions = [m.start() for m in matches]
            else:
                positions = []
                start = 0
                while True:
                    idx = lowered.find(kw, start)
                    if idx < 0:
                        break
                    positions.append(idx)
                    start = idx + len(kw)

            for idx in positions:
                before = lowered[max(0, idx - 15):idx].strip()
                after = lowered[idx + len(kw): idx + len(kw) + 15].strip()
                is_negated = any(
                    before.endswith(neg) or after.startswith(neg)
                    for neg in _NEGATION_WORDS
                )
                candidates.append((ptype, idx, is_negated))
    positive = [c for c in candidates if not c[2]]
    if positive:
        return min(positive, key=lambda c: c[1])[0]
    return None


def _format_recommendation_reply(candidates: List[Dict[str, Any]]) -> str:
    """Deterministic fallback used only if BOTH LLM providers are down -
    never leaves the customer with no reply at all."""
    parts = ["Ji bilkul, in options mein se dekh lijiye:"]
    for c in candidates:
        parts.append(f"{c['title']}, taqreeban {c['price_pkr'] / 10_000_000:.2f} crore, {c['bedrooms']} bedroom.")
    parts.append("Kya in mein se koi appointment ke liye theek lagta hai?")
    return " ".join(parts)


def _recommendation_system_prompt(prefs: Dict[str, Any], objection: Optional[str],
                                    strategy, decline_count: int) -> str:
    known = ", ".join(f"{k}={v}" for k, v in {
        "budget": prefs.get("budget"), "city": prefs.get("city"), "area": prefs.get("area"),
        "bedrooms": prefs.get("bedrooms"), "purpose": prefs.get("purpose"),
    }.items() if v) or "nothing captured yet"

    stop_pushing_note = ""
    if decline_count >= 2:
        stop_pushing_note = (
            "The customer has declined suggestions twice already this call. Do NOT "
            "proactively suggest another alternative property unless they explicitly ask "
            "for one. Acknowledge warmly and ask what else you can help with, or offer "
            "to end the call politely if there is nothing else."
        )

    return node_prompt(
        "RECOMMENDATION",
        known=known,
        stop_pushing_note=stop_pushing_note,
        objection=objection or "none",
        talking_points=("; ".join(strategy.talking_points) if strategy else "none"),
    )


@traced_node("recommendation", annotate=lambda i, o: f"{len(o.get('tool_outputs', {}).get('last_recommendations', []) or [])} candidate(s)")
def recommendation_node(state: AgentState) -> Dict[str, Any]:
    prefs = state["property_preferences"]
    objection = state["intent"].get("objection")
    strategy = build_strategy(objection, state["decline_count"]) if objection else None
    system_prompt = _recommendation_system_prompt(prefs, objection, strategy, state["decline_count"])

    captured: Dict[str, Any] = {"candidates": None, "unresolved": {}}

    def _execute_search_property_tool(name: str, args: Dict[str, Any]) -> Any:
        if name != "search_property_tool":
            return {"error": f"unknown tool {name!r}"}
        args = dict(args)

        city_val, city_bad = _validate_categorical(args.get("city"), structured_retrieval.get_distinct_cities())
        area_val, area_bad = _validate_categorical(args.get("area"), structured_retrieval.get_distinct_areas())

        detected_type = _detect_property_type(state["customer_text"])
        type_val, type_bad = _validate_categorical(
            detected_type or args.get("property_type"), structured_retrieval.get_distinct_property_types())
        args["city"], args["area"], args["property_type"] = city_val, area_val, type_val

        if city_bad:
            captured["unresolved"]["city"] = city_bad
        if area_bad:
            captured["unresolved"]["area"] = area_bad
        if type_bad:
            captured["unresolved"]["property_type"] = type_bad

        results = search_property_tool.invoke(args)
        captured["candidates"] = results
        captured["validated_args"] = args
        print(f"  [recommendation_node] search_property_tool called with "
              f"{args} -> {len(results)} result(s)")

        tool_result: Dict[str, Any] = {"results": results}
        if captured["unresolved"]:
            tool_result["unrecognized_fields"] = dict(captured["unresolved"])
            tool_result["valid_cities"] = structured_retrieval.get_distinct_cities()
            tool_result["valid_areas"] = structured_retrieval.get_distinct_areas()
        return tool_result

    try:
        reply = llm_client.generate_with_tools(
            system_prompt, state["customer_text"], _RECOMMENDATION_TOOL_SCHEMAS,
            _execute_search_property_tool, history=_recent_history(state),
        )
        candidates = captured["candidates"] or []
        validated = captured.get("validated_args", {})
        if not reply or not reply.strip():
            # generate_with_tools() did NOT raise here, but still produced
            # nothing usable - confirmed live: when the primary times out,
            # llm_client's Gemini fallback has NO tool access (see its own
            # docstring), yet this node's system prompt assumes a tool call
            # already happened ("phrase a reply using ONLY what the tool
            # returns"). Gemini can't satisfy that instruction with no tool
            # result to work from, and returned an empty string instead of
            # raising - which is exactly the kind of silent failure that
            # matters most here: live_voice_pipeline.py's mic loop treats
            # `not reply` as "the call is over" and hangs up (confirmed
            # live - no goodbye was said, the empty reply alone ended the
            # call). Falling through to the same deterministic template
            # used when both providers are fully down closes that gap -
            # this reply must never be empty.
            raise RuntimeError("generate_with_tools returned an empty reply")
    except RuntimeError:
        # both LLM providers fully down, OR the primary/Gemini path produced
        # an empty reply above - fall back to the old deterministic path.
        # Prefer results the tool-calling loop already fetched (the LLM may
        # have successfully called search_property_tool before failing to
        # produce final text) over re-running the search from scratch with
        # conversation_memory.py's regex-parsed slots, which may be stale
        # or less specific than what was just extracted this turn.
        if captured["candidates"] is not None:
            candidates = captured["candidates"]
            validated = captured.get("validated_args", prefs)
        else:
            candidates = search_property_tool.invoke({
                "budget": prefs.get("budget"), "city": prefs.get("city"), "area": prefs.get("area"),
                "bedrooms": prefs.get("bedrooms"), "purpose": prefs.get("purpose"),
                "property_type": _detect_property_type(state["customer_text"]) or prefs.get("property_type"),
                "top_n": 3,
            })
            validated = prefs
        reply = _format_recommendation_reply(candidates) if candidates else (
            "Maazrat sir, is waqt system thora slow hai. Aap apna budget aur area "
            "dobara bata dijiye, main filhaal available options dekhta hoon.")

    clarification_needed = bool(captured["unresolved"])
    updated_prefs = dict(prefs)
    for k, v in validated.items():
        # only overwrite a known slot with a NEW non-None value - if this
        # turn's tool call omitted city (because the customer didn't
        # restate it, relying on the "known so far" hint instead), don't
        # let that erase a city captured on an earlier turn
        if k in prefs and v is not None:
            updated_prefs[k] = v
    if candidates:
        updated_prefs.update({
            "last_shown_property_ids": [c["id"] for c in candidates],
            "last_shown_min_price": min(c["price_pkr"] for c in candidates),
            "last_shown_max_price": max(c["price_pkr"] for c in candidates),
        })

    return {
        "agent_reply": reply,
        "conversation_history": _say(state, reply),
        "property_preferences": updated_prefs,
        "tool_outputs": {**state["tool_outputs"], "last_recommendations": candidates},
        "clarification_needed": clarification_needed,
        "missing_fields": list(captured["unresolved"].keys()),
    }


# ---------- 5. Booking (Task 4 validation gate) ----------

_BOOKING_DRAFT_KEY = "booking_draft"

_PROPERTY_SPEECH_ALIASES = {
    "ایک": "1", "ون": "1", "دو": "2", "ٹو": "2", "تین": "3", "تھری": "3",
    "چار": "4", "فور": "4", "پانچ": "5", "فائیو": "5", "چھ": "6", "سکس": "6",
    "سات": "7", "سیون": "7", "آٹھ": "8", "ایٹ": "8", "نو": "9", "نائن": "9",
    "دس": "10", "ٹین": "10", "مرلہ": "marla", "اپارٹمنٹ": "apartment",
    "گھر": "house", "پلاٹ": "plot", "دکان": "shop", "دفتر": "office",
    "گودام": "warehouse",
}


def _normalize_property_speech(text: str) -> str:
    value = (text or "").lower()
    for source in sorted(_PROPERTY_SPEECH_ALIASES, key=len, reverse=True):
        value = re.sub(
            rf"(?<!\w){re.escape(source)}(?!\w)",
            _PROPERTY_SPEECH_ALIASES[source],
            value,
        )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _sync_booking_draft_from_state(
    state: AgentState,
    draft: Dict[str, Any],
) -> Dict[str, Any]:
    """Save every booking detail understood so far.

    Examples:
      "mera naam Ali hai"        -> client_name saved
      "DHA Phase 6"              -> area saved
      "apartment"                -> property_type saved
      "8 August ko 6 baje"       -> datetime saved

    If several facts appear in one utterance, all of them are saved together.
    Later turns never erase earlier booking answers.
    """
    profile = state["user_profile"]
    prefs = state["property_preferences"]
    text = state.get("customer_text", "")

    if profile.get("client_name"):
        draft["client_name"] = profile["client_name"]

    if profile.get("client_phone"):
        draft["client_phone"] = profile["client_phone"]

    for key in ("city", "area", "property_type", "budget", "bedrooms", "purpose"):
        if prefs.get(key) is not None:
            draft[key] = prefs[key]

    # Extra safety net for spoken Urdu / Roman Urdu property-type words.
    detected_type = _detect_property_type(text)
    if detected_type:
        draft["property_type"] = detected_type

    current_dt = parse_appointment_datetime(text)
    if current_dt is not None:
        draft["start_datetime"] = current_dt.isoformat()

    return draft


def _booking_candidates(
    state: AgentState,
    draft: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Find real AVAILABLE properties using accumulated booking context."""
    direct = structured_retrieval.search_properties(
        city=draft.get("city"),
        area=draft.get("area"),
        property_type=draft.get("property_type"),
        max_price=draft.get("budget"),
        status="available",
    )

    if direct:
        return direct

    # Fall back to properties already shown earlier in the same conversation,
    # filtered against whatever the caller has now confirmed.
    prefs = state["property_preferences"]
    shown: List[Dict[str, Any]] = []

    for pid in prefs.get("last_shown_property_ids") or []:
        prop = structured_retrieval.get_property_by_id(pid)

        if not prop or prop.get("status") != "available":
            continue

        if draft.get("area") and prop.get("area") != draft.get("area"):
            continue

        if draft.get("city") and prop.get("city") != draft.get("city"):
            continue

        if (
            draft.get("property_type")
            and prop.get("property_type") != draft.get("property_type")
        ):
            continue

        shown.append(prop)

    return shown



def _hydrate_booking_draft_from_property(
    draft: Dict[str, Any],
    prop: Dict[str, Any],
) -> None:
    """Backfill trusted listing fields after an exact property is selected.

    Once property #33 is resolved from the database, asking the caller to repeat
    "apartment" or the area is unnecessary and error-prone. The listing itself is
    the authoritative source for those fields.
    """
    if not prop:
        return

    draft["property_id"] = prop.get("id")
    draft["property_title"] = prop.get("title")

    for key in ("property_type", "area", "city", "bedrooms"):
        value = prop.get(key)
        if value is not None:
            draft[key] = value


def _resolve_booking_property(
    state: AgentState,
    draft: Dict[str, Any],
) -> tuple:
    """Resolve one specific real property without guessing."""
    stored_id = draft.get("property_id")

    if stored_id:
        prop = structured_retrieval.get_property_by_id(int(stored_id))
        if prop and prop.get("status") == "available":
            _hydrate_booking_draft_from_property(draft, prop)
            return prop, [prop]

    text = state.get("customer_text", "")

    explicit_id = _extract_mentioned_property_id(text)
    if explicit_id:
        prop = structured_retrieval.get_property_by_id(explicit_id)
        if prop and prop.get("status") == "available":
            _hydrate_booking_draft_from_property(draft, prop)
            return prop, [prop]

    # We first collect area + property type naturally before asking the caller
    # to choose an exact listing.
    if not draft.get("area") or not draft.get("property_type"):
        return None, []

    candidates = _booking_candidates(state, draft)

    # If there is exactly one legitimate matching property, selection is
    # unambiguous.
    if len(candidates) == 1:
        prop = candidates[0]
        _hydrate_booking_draft_from_property(draft, prop)
        return prop, candidates

    spoken = set(_normalize_property_speech(text).split())
    stop = {
        "in", "dha", "phase", "lahore", "karachi", "islamabad",
        "property", "the",
    }

    best: List[Dict[str, Any]] = []
    best_score = 0

    for prop in candidates:
        title_tokens = (
            set(_normalize_property_speech(prop.get("title", "")).split()) - stop
        )
        score = len(spoken & title_tokens)

        if score > best_score:
            best_score = score
            best = [prop]
        elif score == best_score and score:
            best.append(prop)

    # With multiple candidates, require enough identifying information to
    # avoid silently choosing the wrong listing.
    if best_score >= 2 and len(best) == 1:
        prop = best[0]
        _hydrate_booking_draft_from_property(draft, prop)
        return prop, candidates

    return None, candidates


def _property_choice_reply(candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return (
            "Is combination mein abhi koi available property nazar nahi aa rahi. "
            "Kya aap koi doosra area ya property type try karna chahenge?"
        )

    titles = [
        p.get("title", f"Property {p.get('id')}")
        for p in candidates[:4]
    ]

    if len(titles) == 1:
        return f"Kya aap {titles[0]} ki visit book karna chahte hain?"

    options = "; ".join(
        f"{i + 1}) {title}"
        for i, title in enumerate(titles)
    )

    return (
        f"Is area mein yeh options available hain: {options}. "
        "In mein se kaunsi property dekhna chahenge?"
    )


def _next_booking_question(
    field: str,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Ask for exactly ONE missing booking detail."""
    if field == "client_name":
        return "Ji, sab se pehle aap ka naam bata dijiye."

    if field == "area":
        return "Ji, kis area mein property dekhna chahenge?"

    if field == "property_type":
        return (
            "Ji, kis type ki property dekhna chahenge — "
            "apartment, house, plot, shop ya office?"
        )

    if field == "property":
        return _property_choice_reply(candidates or [])

    if field == "date_time":
        return "Ji, visit ke liye kaunsa din aur waqt suit karega?"

    return "Ji, booking complete karne ke liye thori si aur detail chahiye."


@traced_node("booking", annotate=lambda i, o: o.get("agent_reply", "")[:70])
def booking_node(state: AgentState) -> Dict[str, Any]:
    """Progressive multi-turn booking.

    Every useful fact from the caller is stored immediately in
    ``tool_outputs.booking_draft``. The agent then asks only for the NEXT
    missing detail, instead of dumping a full checklist.

    Example:
        caller: "mera naam Ali hai"
        -> saves Ali
        -> asks area

        caller: "DHA Phase 6"
        -> saves area
        -> asks property type

        caller: "apartment"
        -> saves type
        -> asks which exact apartment if several match

        caller: "8 August ko 6 baje"
        -> saves datetime
        -> books immediately if all other slots are already complete
    """
    prefs = state["property_preferences"]
    is_seller = state["intent"].get("call_intent") == "seller_inquiry"

    draft = dict(
        (state.get("tool_outputs") or {}).get(_BOOKING_DRAFT_KEY) or {}
    )

    # Save ALL facts recognized on this turn before deciding what to ask.
    draft = _sync_booking_draft_from_state(state, draft)

    parsed_dt = None
    if draft.get("start_datetime"):
        try:
            parsed_dt = datetime.fromisoformat(draft["start_datetime"])
        except (TypeError, ValueError):
            draft.pop("start_datetime", None)

    # Phone is supplied by telephony metadata, never requested from speech.
    if not draft.get("client_phone"):
        reply = (
            "Maazrat sir, call ki contact details system mein load nahi ho rahi. "
            "Main booking ko abhi finalize nahi kar sakta."
        )

        crm_log_tool.invoke({
            "session_id": state["session_id"],
            "event_type": "caller_id_missing",
            "payload": {"reason": "telephony caller_id was not provided"},
            "status": "failed",
        })

        return _write_action_update(
            state,
            "book",
            False,
            reply,
            missing_fields=[],
            clarification_needed=False,
            tool_outputs={_BOOKING_DRAFT_KEY: draft},
        )

    property_info = None
    candidates: List[Dict[str, Any]] = []

    if is_seller:
        descriptor = " ".join(
            value
            for value in [
                draft.get("property_type") or prefs.get("property_type"),
                draft.get("area") or prefs.get("area"),
                draft.get("city") or prefs.get("city"),
            ]
            if value
        )

        property_info = {
            "id": None,
            "title": (
                f"Property Valuation - {descriptor}"
                if descriptor
                else "Property Valuation Visit"
            ),
        }
        draft["property_title"] = property_info["title"]

    else:
        property_info, candidates = _resolve_booking_property(state, draft)

    # Ask ONE missing item only. Everything already known is skipped.
    pending_name = (state.get("tool_outputs") or {}).get("pending_name_confirmation")

    if pending_name and not draft.get("client_name"):
        next_missing = "confirm_name"
    elif not draft.get("client_name"):
        next_missing = "client_name"

    elif not is_seller and not draft.get("area"):
        next_missing = "area"

    elif not is_seller and not draft.get("property_type"):
        next_missing = "property_type"

    elif not is_seller and property_info is None:
        next_missing = "property"

    elif parsed_dt is None:
        next_missing = "date_time"

    else:
        next_missing = None

    if next_missing is not None:
        if next_missing == "confirm_name":
            candidate = pending_name.get("candidate", "")
            reply = f"Aap ka naam {candidate} hai, correct?"
        else:
            reply = _next_booking_question(next_missing, candidates)

        return _write_action_update(
            state,
            "book",
            False,
            reply,
            missing_fields=[next_missing],
            clarification_needed=True,
            tool_outputs={_BOOKING_DRAFT_KEY: draft},
        )

    # Every required slot now exists. Validate Calendar availability.
    availability = check_availability_tool.invoke({
        "start_datetime_iso": parsed_dt.isoformat()
    })

    if not availability["available"]:
        when = parsed_dt.strftime("%A, %d %B %Y at %I:%M %p")

        # Only clear the rejected time. Name/area/type/property remain saved.
        draft.pop("start_datetime", None)

        reply = (
            f"Maazrat sir, {when} ka waqt already book hai. "
            "Koi aur din ya waqt bata dijiye."
        )

        return _write_action_update(
            state,
            "book",
            False,
            reply,
            missing_fields=["date_time"],
            clarification_needed=True,
            tool_outputs={
                _BOOKING_DRAFT_KEY: draft,
                "last_availability": availability,
            },
        )

    booking = book_calendar_tool.invoke({
        "client_name": draft["client_name"],
        "client_phone": draft["client_phone"],
        "property_title": property_info["title"],
        "property_id": property_info["id"],
        "start_datetime_iso": parsed_dt.isoformat(),
        **({
            "meeting_notes": (
                "Seller valuation visit - customer offered this property "
                "for sale/listing"
            )
        } if is_seller else {}),
    })

    if not booking["success"]:
        reply = (
            f"Maazrat sir, booking mein masla aa gaya: {booking['error']}. "
            "Thori dair baad dobara try karte hain."
        )

        crm_log_tool.invoke({
            "session_id": state["session_id"],
            "event_type": "calendar_failed",
            "payload": {"error": booking["error"]},
            "status": "failed",
        })

        return _write_action_update(
            state,
            "book",
            False,
            reply,
            clarification_needed=False,
            tool_outputs={_BOOKING_DRAFT_KEY: draft},
        )

    when = parsed_dt.strftime("%A, %d %B %Y at %I:%M %p")

    reply = (
        f"Ji bilkul {draft['client_name']} sahab, aap ki appointment "
        f"{property_info['title']} ke liye {when} ko confirm ho gayi hai. "
        "Confirmation aur appointment details bhej di jayengi."
    )

    appointment_status = {
        "event_id": booking["event_id"],
        "property_title": property_info["title"],
        "property_id": property_info["id"],
        "start_datetime": parsed_dt.isoformat(),
        "employee_name": "RealEstate Hub Agent",
        "employee_email": None,
        "status": "booked",
    }

    crm_log_tool.invoke({
        "session_id": state["session_id"],
        "event_type": "appointment_booked",
        "payload": {"event_id": booking["event_id"]},
    })
    history_result = crm_logger.log_appointment_history(
        state["session_id"],
        "booked",
        client_phone=draft.get("client_phone"),
        client_name=draft.get("client_name"),
        property_id=property_info.get("id"),
        property_title=property_info.get("title"),
        start_datetime=parsed_dt.isoformat(),
        event_id=booking.get("event_id"),
    )
    if history_result.success:
        print(
            f"[crm] appointment_history saved id={history_result.log_id} "
            f"status=booked event_id={booking.get('event_id')}"
        )
    else:
        print(
            f"[crm] FAILED to save appointment_history status=booked: "
            f"{history_result.error}"
        )

    # Booking finished: clear only the temporary draft.
    cleaned_outputs = dict(state["tool_outputs"])
    cleaned_outputs.pop(_BOOKING_DRAFT_KEY, None)

    return _write_action_update(
        state,
        "book",
        True,
        reply,
        clarification_needed=False,
        missing_fields=[],
        appointment_status=appointment_status,
        tool_outputs=cleaned_outputs,
    )


# ---------- 6. Rescheduling (Task 4 validation gate) ----------

@traced_node("rescheduling", annotate=lambda i, o: o.get("agent_reply", "")[:70])
def rescheduling_node(state: AgentState) -> Dict[str, Any]:
    """Same gate shape as booking_node. Uses parse_reschedule_datetime()
    (this project's fix for sentences that mention both the original and
    the newly requested date/time - a plain single-date parse would
    silently grab whichever one appears first) then re-checks availability
    for the NEW slot before ever calling reschedule_calendar_tool."""
    text = state["customer_text"]
    pending = state["appointment_status"]

    if not pending or not pending.get("event_id"):
        reply = ("Maazrat sir, is call mein mujhe koi existing appointment nazar nahi aa rahi. "
                 "Kya main nai appointment book kar doon?")
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=True)

    new_dt = parse_reschedule_datetime(text)
    if not new_dt:
        old_when = datetime.fromisoformat(pending["start_datetime"]).strftime("%A, %d %B %Y at %I:%M %p")
        reply = f"Aap ki current appointment {old_when} ke liye hai. Naya din aur waqt bata dijiye."
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=True)

    availability = check_availability_tool.invoke({"start_datetime_iso": new_dt.isoformat()})
    if not availability["available"]:
        when = new_dt.strftime("%A, %d %B %Y at %I:%M %p")
        reply = f"Maazrat sir, {when} bhi already book hai. Koi aur waqt bata dijiye?"
        return _write_action_update(
            state, "reschedule", False, reply, clarification_needed=True,
            tool_outputs={**state["tool_outputs"], "last_availability": availability},
        )

    old_start = pending["start_datetime"]
    result = reschedule_calendar_tool.invoke({
        "event_id": pending["event_id"], "new_start_datetime_iso": new_dt.isoformat(),
    })
    if not result["success"]:
        reply = f"Maazrat sir, reschedule mein masla aa gaya: {result['error']}."
        crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "calendar_failed", "payload": {"operation": "reschedule", "error": result.get("error")}, "status": "failed"})
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=False)

    when = new_dt.strftime("%A, %d %B %Y at %I:%M %p")
    reply = f"Ji bilkul, appointment ab {when} ke liye reschedule ho gayi hai."
    # _old_start_datetime is a transient hint for email_node only, stripped
    # back out once the email step reads it (see email_node below)
    new_status = {**pending, "start_datetime": new_dt.isoformat(), "status": "rescheduled",
                  "_old_start_datetime": old_start}
    crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "appointment_rescheduled",
                          "payload": {"event_id": pending["event_id"], "old_start": old_start,
                                      "new_start": new_dt.isoformat()}})
    profile = state.get("user_profile") or {}
    history_result = crm_logger.log_appointment_history(
        state["session_id"],
        "rescheduled",
        client_phone=profile.get("client_phone") or state.get("caller_id"),
        client_name=profile.get("client_name"),
        property_id=pending.get("property_id"),
        property_title=pending.get("property_title"),
        start_datetime=new_dt.isoformat(),
        event_id=pending.get("event_id"),
    )
    if history_result.success:
        print(
            f"[crm] appointment_history saved id={history_result.log_id} "
            f"status=rescheduled event_id={pending.get('event_id')}"
        )
    else:
        print(
            f"[crm] FAILED to save appointment_history status=rescheduled: "
            f"{history_result.error}"
        )
    return _write_action_update(state, "reschedule", True, reply, clarification_needed=False,
                                 appointment_status=new_status)


# ---------- 7. Cancellation ----------

@traced_node("cancellation", annotate=lambda i, o: o.get("agent_reply", "")[:70])
def cancellation_node(state: AgentState) -> Dict[str, Any]:
    text = state["customer_text"]
    pending = state["appointment_status"]

    # Guard: if the appointment is already marked cancelled in state (e.g. the
    # previous turn's cancellation succeeded but the intent stayed sticky and
    # re-routed here on the follow-up turn), do not attempt a second cancel.
    if pending and pending.get("status") == "cancelled":
        reply = (
            "Ji sir, aap ki appointment pehle hi cancel ho chuki hai. "
            "Kya main aap ki kisi aur tarah madad kar sakta hoon?"
        )
        # Return success=True so _route_after_write_action does NOT escalate,
        # but skip the email node since nothing new happened on Calendar.
        # We short-circuit to END by clearing last_write_action success so the
        # graph takes the END branch (clarification_needed=True keeps it there).
        return _write_action_update(state, "cancel", False, reply, clarification_needed=True)

    if not pending or not pending.get("event_id"):
        reply = "Maazrat sir, is call mein mujhe koi existing appointment nazar nahi aa rahi jise cancel karoon."
        return _write_action_update(state, "cancel", False, reply, clarification_needed=True)

    result = cancel_calendar_tool.invoke({"event_id": pending["event_id"], "reason": text})
    if not result["success"]:
        reply = f"Maazrat sir, cancel karne mein masla aa gaya: {result['error']}."
        crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "calendar_failed", "payload": {"operation": "cancel", "error": result.get("error")}, "status": "failed"})
        return _write_action_update(state, "cancel", False, reply, clarification_needed=False)

    reply = "Ji theek hai, aap ki appointment cancel kar di gayi hai. Jab bhi ready hon, hum yahan hain."
    new_status = {**pending, "status": "cancelled", "_cancel_reason": text}
    crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "appointment_cancelled",
                          "payload": {"event_id": pending["event_id"], "reason": text}})
    profile = state.get("user_profile") or {}
    history_result = crm_logger.log_appointment_history(
        state["session_id"],
        "cancelled",
        client_phone=profile.get("client_phone") or state.get("caller_id"),
        client_name=profile.get("client_name"),
        property_id=pending.get("property_id"),
        property_title=pending.get("property_title"),
        start_datetime=pending.get("start_datetime"),
        event_id=pending.get("event_id"),
    )
    if history_result.success:
        print(
            f"[crm] appointment_history saved id={history_result.log_id} "
            f"status=cancelled event_id={pending.get('event_id')}"
        )
    else:
        print(
            f"[crm] FAILED to save appointment_history status=cancelled: "
            f"{history_result.error}"
        )
    return _write_action_update(state, "cancel", True, reply, clarification_needed=False,
                                 appointment_status=new_status)


# ---------- 8. Email ----------

@traced_node("email", annotate=lambda i, o: (
    "email sent" if (o.get("tool_outputs", {}) or {}).get("last_email", {}).get("success") else "email failed"
))
def email_node(state: AgentState) -> Dict[str, Any]:
    """Shared node all three write-actions route through after a
    successful calendar op - mirrors the n8n workflow's own separate
    email-notify step (Day 4 Task 2), kept as its own graph node here too
    so Day 5's structure matches Day 4's automation shape 1:1."""
    kind = state["tool_outputs"].get("last_write_action", {}).get("kind", "book")
    profile = state["user_profile"]
    pending = state["appointment_status"] or {}
    prefs = state["property_preferences"]

    requirement_lines = []
    if prefs.get("budget"):
        requirement_lines.append(f"Budget: PKR {prefs['budget']:,}")
    if prefs.get("area"):
        requirement_lines.append(f"Area: {prefs['area']}")
    if prefs.get("purpose"):
        requirement_lines.append(f"Purpose: {prefs['purpose']}")
    requirements_text = "\n".join(requirement_lines) or "No specific requirements captured on the call."

    result = email_tool.invoke({
        "kind": kind,
        "client_name": profile.get("client_name") or "Unknown",
        "client_phone": profile.get("client_phone") or "Not provided",
        "property_title": pending.get("property_title", "Unknown property"),
        "property_id": pending.get("property_id"),
        "start_datetime_iso": pending.get("start_datetime"),
        "requirements_text": requirements_text,
        "old_start_datetime_iso": pending.get("_old_start_datetime"),
        "reason": pending.get("_cancel_reason", ""),
        "client_email": profile.get("client_email"),  # CC the customer if they gave their email
    })

    crm_log_tool.invoke({
        "session_id": state["session_id"],
        "event_type": "email_sent" if result["success"] else "email_failed",
        "payload": {"kind": kind, "message_id": result.get("message_id"), "error": result.get("error")},
        "status": "success" if result["success"] else "failed",
    })

    cleaned_status = {k: v for k, v in pending.items() if not k.startswith("_")}
    return {
        "appointment_status": cleaned_status,
        "tool_outputs": {**state["tool_outputs"], "last_email": result},
    }


# ---------- 9. Escalation ----------

_ESCALATION_REPLY = (
    "Ji zaroor sir, main aap ko hamare senior agent se connect kar deta hoon jo "
    "yeh behtar handle kar sakein. Wo jald hi aap se rabta karenge."
)


@traced_node("escalation", annotate=lambda i, o: "escalated to human agent")
def escalation_node(state: AgentState) -> Dict[str, Any]:
    """Day 1 ESCALATION RULES, the one node that never tries to resolve
    anything itself: explicit human request (detect_escalation_request,
    checked first by graph.py's router) or a real technical failure on a
    write action (routed here by _route_after_write_action when a
    booking/reschedule/cancel fails for a reason other than missing info or
    an unavailable slot). Always logs the reason to CRM and tells the
    customer clearly a human will follow up, per system_prompt.md."""
    last_write = state["tool_outputs"].get("last_write_action", {})
    reason = "customer_requested_human" if detect_escalation_request(state["customer_text"]) else (
        f"technical_failure:{last_write.get('kind')}" if last_write and not last_write.get("success")
        else "unresolved_after_multiple_attempts"
    )
    crm_log_tool.invoke({
        "session_id": state["session_id"], "event_type": "escalated_to_human",
        "payload": {"reason": reason}, "status": "escalated",
    })
    return {"agent_reply": _ESCALATION_REPLY, "conversation_history": _say(state, _ESCALATION_REPLY)}


# ---------- 10. Goodbye ----------

@traced_node("goodbye", annotate=lambda i, o: "call closed")
def goodbye_node(state: AgentState) -> Dict[str, Any]:
    reply = "Shukriya sir, aap ka waqt dene ke liye. Allah Hafiz, aur zaroorat par hum yahan hain."
    return {"agent_reply": reply, "conversation_history": _say(state, reply)}