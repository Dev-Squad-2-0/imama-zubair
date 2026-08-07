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

import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_core.utils.function_calling import convert_to_openai_tool

from state import AgentState, slots_from_text
from graph_logger import traced_node
import llm_client
from call_intent import classify_call_intent
from appointment_intent import detect_appointment_intent, parse_appointment_datetime, parse_reschedule_datetime
from objection_handler import detect_objection, build_strategy, should_stop_pushing
from conversation_memory import _PK_MOBILE_SHAPE
import crm_logger
import structured_retrieval
from tools import (
    search_property_tool, check_availability_tool, book_calendar_tool,
    reschedule_calendar_tool, cancel_calendar_tool, email_tool, crm_log_tool,
    rag_search_tool, property_lookup_tool,
)


# ---------- shared helpers ----------

def _say(state: AgentState, reply: str) -> List[Dict[str, str]]:
    return state["conversation_history"] + [{"speaker": "agent", "text": reply}]


_PROPERTY_ID_PATTERN = re.compile(r"property\s*(?:number|no\.?|#)?\s*(\d+)", re.IGNORECASE)


def _extract_mentioned_property_id(customer_text: str) -> Optional[int]:
    m = _PROPERTY_ID_PATTERN.search(customer_text)
    return int(m.group(1)) if m else None


def _write_action_update(state: AgentState, kind: str, success: bool, agent_reply: str,
                          **extra: Any) -> Dict[str, Any]:
    """Every booking/reschedule/cancel code path returns through this, so
    graph.py's post-write conditional edge (route to email only on real
    success) always has tool_outputs.last_write_action to read - impossible
    to forget to set it on one branch and not another."""
    return {
        "agent_reply": agent_reply,
        "conversation_history": _say(state, agent_reply),
        "tool_outputs": {**state["tool_outputs"], "last_write_action": {"kind": kind, "success": success}},
        **extra,
    }


# ---------- 1. Greeting ----------

_GREETING_LINE = (
    "Assalam-o-Alaikum sir! RealEstate Hub se baat ho rahi hai. "
    "Main aap ki kis tarah madad kar sakta hoon?"
)


@traced_node("greeting", annotate=lambda i, o: "opening line sent")
def greeting_node(state: AgentState) -> Dict[str, Any]:
    """Fires only on a call-start invocation (empty customer_text AND not
    yet greeted, see graph.py's entry router) - the agent's opening line,
    before there's anything from the customer to route on. Sets greeted=True
    so a later re-invocation with empty customer_text (a retried call, a UI
    rerun) doesn't replay this line."""
    return {"agent_reply": _GREETING_LINE, "conversation_history": _say(state, _GREETING_LINE), "greeted": True}


# ---------- 2. Intent Detection ----------

_GOODBYE_KEYWORDS = [
    "shukriya", "thank you", "thanks", "bye", "khuda hafiz", "allah hafiz",
    "theek hai bas", "bas itna hi", "koi masla nahi",
]


def is_goodbye_turn(state: AgentState) -> bool:
    """Closing language, or Day 3's existing 2-decline stop-pushing rule
    (objection_handler.should_stop_pushing) - checked by graph.py's router,
    not a node itself."""
    lowered = state["customer_text"].lower()
    if any(kw in lowered for kw in _GOODBYE_KEYWORDS):
        return True
    return should_stop_pushing(state["decline_count"])


def _annotate_intent(_inp, out):
    intent = out.get("intent", {})
    return f"call_intent={intent.get('call_intent')}, appointment_intent={intent.get('appointment_intent')}"


@traced_node("intent_detection", annotate=_annotate_intent)
def intent_detection_node(state: AgentState) -> Dict[str, Any]:
    """Classifies this turn (Day 4's keyword classifiers, not an LLM call -
    see module docstring) and updates user_profile/property_preferences by
    reusing conversation_memory.py's proven slot parsers via
    state.slots_from_text() - no re-implementation of that extraction
    logic."""
    text = state["customer_text"]
    updates = slots_from_text(state["user_profile"], state["property_preferences"],
                               state["decline_count"], text)

    intent = {
        "call_intent": classify_call_intent(text),
        "appointment_intent": detect_appointment_intent(text),
        "objection": detect_objection(text),
    }

    return {
        **updates,
        "conversation_history": state["conversation_history"] + [{"speaker": "customer", "text": text}],
        "intent": intent,
    }


# ---------- 3. RAG (the one node with real LLM tool-calling) ----------

_RAG_SYSTEM_PROMPT = (
    "You are a real estate assistant answering a factual question from a phone "
    "customer. You have two tools: rag_search_tool for semantic search over "
    "brochures/descriptions/FAQs, and property_lookup_tool for an exact field on "
    "a known property id (price, availability, size, agent contact). Use whichever "
    "tool actually answers the question - property_lookup_tool when a specific "
    "property id is already known and the question is one hard fact, otherwise "
    "rag_search_tool. Answer ONLY using what the tool(s) return; if the tools "
    "don't contain the answer, say honestly that you don't have that information "
    "rather than guessing. Reply in natural Pakistani UrduLish, under 80 words, "
    "plain spoken sentences, no markdown."
)

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
    try:
        reply = llm_client.generate_with_tools(
            _RAG_SYSTEM_PROMPT, state["customer_text"] + hint, _RAG_TOOL_SCHEMAS, _execute_rag_tool,
        )
    except RuntimeError as e:
        reply = "Maazrat sir, is waqt yeh maloomat nikalne mein masla ho raha hai, thori dair baad dobara poochein."
    return {"agent_reply": reply, "conversation_history": _say(state, reply)}


# ---------- 4. Recommendation (deterministic tool call + objection-aware phrasing) ----------

def _format_recommendation_reply(candidates: List[Dict[str, Any]]) -> str:
    """Deterministic fallback used only if BOTH LLM providers are down -
    never leaves the customer with no reply at all."""
    parts = ["Ji bilkul, in options mein se dekh lijiye:"]
    for c in candidates:
        parts.append(f"{c['title']}, taqreeban {c['price_pkr'] / 10_000_000:.2f} crore, {c['bedrooms']} bedroom.")
    parts.append("Kya in mein se koi appointment ke liye theek lagta hai?")
    return " ".join(parts)


_RECOMMENDATION_SYSTEM_PROMPT = """You are Ali, a warm professional Pakistani real estate agent speaking UrduLish on a phone call.
Rules: never invent prices/availability/amenities beyond what's listed below; if the customer raised an objection, acknowledge it before offering an alternative; never guarantee investment returns; always leave an easy exit ("no commitment needed"); reply under 80 words, plain spoken sentences, no markdown.

Candidates:
{candidates}

Objection detected: {objection}
Talking points for that objection (use these, don't invent your own): {talking_points}"""


@traced_node("recommendation", annotate=lambda i, o: f"{len(o.get('tool_outputs', {}).get('last_recommendations', []) or [])} candidate(s)")
def recommendation_node(state: AgentState) -> Dict[str, Any]:
    """search_property_tool is called deterministically here (not an LLM
    choice) - recommending always runs the same search given whatever
    preferences are known, matching Day 4's /property-match endpoint. The
    LLM (if reachable) only phrases the reply naturally and, when an
    objection was detected this turn, folds in objection_handler.py's
    strategy - it does not decide WHAT to recommend, only how to say it."""
    prefs = state["property_preferences"]
    candidates = search_property_tool.invoke({
        "budget": prefs.get("budget"), "city": prefs.get("city"), "area": prefs.get("area"),
        "bedrooms": prefs.get("bedrooms"), "purpose": prefs.get("purpose"), "top_n": 3,
    })

    if not candidates:
        reply = ("Maazrat sir, abhi in requirements ke mutabiq koi property available nahi hai. "
                 "Kya main budget ya area thora adjust kar ke dobara dekhoon?")
        updated_prefs = prefs
    else:
        objection = state["intent"].get("objection")
        strategy = build_strategy(objection, state["decline_count"]) if objection else None
        candidates_text = "\n".join(
            f"- {c['title']}: PKR {c['price_pkr']:,}, {c['bedrooms']} bedroom, {c['area']}, "
            f"amenities: {c['amenities']}"
            for c in candidates
        )
        system_prompt = _RECOMMENDATION_SYSTEM_PROMPT.format(
            candidates=candidates_text, objection=objection or "none",
            talking_points="; ".join(strategy.talking_points) if strategy else "none",
        )
        try:
            reply = llm_client.generate_reply(system_prompt, state["customer_text"])
        except RuntimeError:
            reply = _format_recommendation_reply(candidates)

        updated_prefs = {
            **prefs,
            "last_shown_property_ids": [c["id"] for c in candidates],
            "last_shown_min_price": min(c["price_pkr"] for c in candidates),
            "last_shown_max_price": max(c["price_pkr"] for c in candidates),
        }

    return {
        "agent_reply": reply,
        "conversation_history": _say(state, reply),
        "property_preferences": updated_prefs,
        "tool_outputs": {**state["tool_outputs"], "last_recommendations": candidates},
    }


# ---------- 5. Booking (Task 4 validation gate) ----------

_MISSING_FIELD_ASKS = {
    "client_name": "aap ka poora naam",
    "client_phone": "aap ka contact number",
    "property": "kaunsi property mein interested hain",
    "date_time": "kaunsa din aur waqt suit karega",
    "time_only": "kaunsa waqt suit karega",
}


def _clarification_reply(missing: List[str]) -> str:
    asks = [_MISSING_FIELD_ASKS.get(f, f) for f in missing]
    return f"Ji zaroor, appointment book karne se pehle bas {', '.join(asks)} bata dijiye."


def _resolve_turn_datetime(state: AgentState, text: str, parse_fn) -> tuple:
    """Resolves the date/time for this turn's booking/reschedule attempt,
    remembering it across turns the same way name/phone/budget already
    accumulate in user_profile/property_preferences - appointment date/time
    didn't before, which meant a date the customer gave one turn (e.g.
    "kal 5 baje appointment book karni hai") could get silently forgotten
    if the very next turn was just a one-word reply to something else the
    agent asked in between (most commonly now: confirming a phone number -
    see conversation_memory.py's confirmation flow). A confidently-parsed
    mention THIS turn always wins and updates what's remembered; only when
    this turn's text has nothing usable does it fall back to a date/time
    already given earlier in the call.

    Returns (datetime_or_None, had_explicit_clock, updated_pending_iso) -
    callers should thread updated_pending_iso back into
    pending_appointment_datetime on every return path (clarification AND
    success), and clear it (None) once a booking/reschedule actually
    succeeds, since it's been consumed into appointment_status by then."""
    parsed = parse_fn(text)
    if parsed and parsed[1]:
        dt, _ = parsed
        return dt, True, dt.isoformat()

    pending_iso = state.get("pending_appointment_datetime")
    if pending_iso:
        return datetime.fromisoformat(pending_iso), True, pending_iso

    if parsed:  # a day was found this turn but no explicit clock, and nothing remembered either
        dt, _ = parsed
        return dt, False, None

    return None, True, None


def _find_appointment_by_phone(client_phone: Optional[str]) -> Optional[Dict[str, Any]]:
    """Cross-session fallback for rescheduling_node/cancellation_node: a
    customer who booked on one call and calls back later has an empty
    appointment_status in this brand-new session (SessionStore is
    in-memory, per session_id, and starts fresh every call) even though
    crm_logger's appointment_history table already has the answer. Returns
    the most recent non-cancelled appointment for this phone number,
    reshaped into the same dict shape appointment_status normally holds, or
    None if there isn't one (or the phone isn't known yet)."""
    if not client_phone:
        return None
    history = crm_logger.get_appointment_history(client_phone)
    for row in reversed(history):  # most recently logged first
        if row.get("status") != "cancelled":
            return {
                "event_id": row.get("event_id"), "property_title": row.get("property_title"),
                "property_id": row.get("property_id"), "start_datetime": row.get("start_datetime"),
                "employee_name": "RealEstate Hub Agent", "employee_email": None,
                "status": row.get("status"),
            }
    return None


def _phone_clarification_reply(profile: Dict[str, Any]) -> Optional[str]:
    """Dedicated phone-confirmation/re-ask reply, asked on its own instead
    of folded into the generic multi-field clarification list - a yes/no
    read-back question reads oddly buried in "please tell me your name,
    confirm your phone, and pick a property." Returns None if the phone
    doesn't need special handling right now (nothing heard yet at all -
    the generic clarification list's plain "aap ka contact number" ask
    already covers that case)."""
    pending = profile.get("client_phone_pending")
    if not pending:
        return None
    if _PK_MOBILE_SHAPE.match(pending):
        formatted = f"{pending[:4]}-{pending[4:]}"
        return f"Maine {formatted} number liya hai, kya yeh sahi hai?"
    return (f"Mujhe sirf {len(pending)} digits samajh aaye, aap apna 11 digit ka "
            f"mobile number dobara bata dijiye.")


@traced_node("booking", annotate=lambda i, o: o.get("agent_reply", "")[:70])
def booking_node(state: AgentState) -> Dict[str, Any]:
    """Task 4's gate: required slots must ALL be present (never guess a
    name/phone/property/date - ask instead), then check_availability_tool
    must confirm the slot is free (never book an unavailable slot) - only
    then does book_calendar_tool run. Mirrors Day 4's appointment/prepare
    -> calendar/create split, now as validation-then-action inside one
    node."""
    profile = state["user_profile"]
    prefs = state["property_preferences"]
    text = state["customer_text"]

    parsed_dt, had_explicit_clock, pending_dt_iso = _resolve_turn_datetime(state, text, parse_appointment_datetime)
    property_id = prefs["last_shown_property_ids"][0] if prefs.get("last_shown_property_ids") else None
    property_info = structured_retrieval.get_property_by_id(property_id) if property_id else None

    missing = []
    if not profile.get("client_name"):
        missing.append("client_name")
    if not (profile.get("client_phone") and profile.get("client_phone_confirmed")):
        missing.append("client_phone")
    if not property_info:
        missing.append("property")
    if not parsed_dt:
        missing.append("date_time")
    elif not had_explicit_clock:
        # a day was understood ("kal") but no clock time was confidently
        # resolved - ask instead of silently booking on the noon default
        missing.append("time_only")

    if missing:
        phone_reply = _phone_clarification_reply(profile) if "client_phone" in missing else None
        reply = phone_reply or _clarification_reply(missing)
        return _write_action_update(state, "book", False, reply, missing_fields=missing,
                                     clarification_needed=True, pending_appointment_datetime=pending_dt_iso)

    availability = check_availability_tool.invoke({"start_datetime_iso": parsed_dt.isoformat()})
    if not availability["available"]:
        when = parsed_dt.strftime("%A, %d %B %Y at %I:%M %p")
        reply = f"Maazrat sir, {when} ka waqt already book hai. Kya koi aur din ya waqt theek rahega?"
        return _write_action_update(
            state, "book", False, reply, missing_fields=[], clarification_needed=True,
            tool_outputs={**state["tool_outputs"], "last_availability": availability},
            pending_appointment_datetime=pending_dt_iso,
        )

    booking = book_calendar_tool.invoke({
        "client_name": profile["client_name"], "client_phone": profile["client_phone"],
        "property_title": property_info["title"], "property_id": property_info["id"],
        "start_datetime_iso": parsed_dt.isoformat(),
    })

    if not booking["success"]:
        reply = f"Maazrat sir, booking mein masla aa gaya: {booking['error']}. Thori dair baad dobara try karte hain."
        crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "calendar_failed",
                              "payload": {"error": booking["error"]}, "status": "failed"})
        return _write_action_update(state, "book", False, reply, clarification_needed=False,
                                     pending_appointment_datetime=pending_dt_iso)

    when = parsed_dt.strftime("%A, %d %B %Y at %I:%M %p")
    reply = f"Ji bilkul sir, aap ki appointment {when} ke liye confirm ho gayi hai."
    appointment_status = {
        "event_id": booking["event_id"], "property_title": property_info["title"],
        "property_id": property_info["id"], "start_datetime": parsed_dt.isoformat(),
        "employee_name": "RealEstate Hub Agent", "employee_email": None, "status": "booked",
    }
    crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "appointment_booked",
                          "payload": {"event_id": booking["event_id"]}})
    crm_logger.log_appointment_history(
        state["session_id"], "booked", client_phone=profile["client_phone"], client_name=profile["client_name"],
        property_id=property_info["id"], property_title=property_info["title"],
        start_datetime=parsed_dt.isoformat(), event_id=booking["event_id"],
    )
    return _write_action_update(state, "book", True, reply, clarification_needed=False,
                                 missing_fields=[], appointment_status=appointment_status,
                                 pending_appointment_datetime=None)


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
        # this session hasn't booked anything yet, but the customer may be
        # calling back about an appointment from an earlier session
        pending = _find_appointment_by_phone(state["user_profile"].get("client_phone"))

    if not pending or not pending.get("event_id"):
        reply = ("Maazrat sir, is call mein mujhe koi existing appointment nazar nahi aa rahi. "
                 "Kya main nai appointment book kar doon?")
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=True)

    new_dt, had_explicit_clock, pending_dt_iso = _resolve_turn_datetime(state, text, parse_reschedule_datetime)
    if not new_dt:
        old_when = datetime.fromisoformat(pending["start_datetime"]).strftime("%A, %d %B %Y at %I:%M %p")
        reply = f"Aap ki current appointment {old_when} ke liye hai. Naya din aur waqt bata dijiye."
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=True,
                                     pending_appointment_datetime=pending_dt_iso)

    if not had_explicit_clock:
        # a new day was understood but no clock time was confidently
        # resolved - ask instead of silently rescheduling to the noon default
        reply = "Ji zaroor, naya din to samajh gaya - bas waqt bata dijiye kaunsa suit karega."
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=True,
                                     pending_appointment_datetime=pending_dt_iso)

    availability = check_availability_tool.invoke({"start_datetime_iso": new_dt.isoformat()})
    if not availability["available"]:
        when = new_dt.strftime("%A, %d %B %Y at %I:%M %p")
        reply = f"Maazrat sir, {when} bhi already book hai. Koi aur waqt bata dijiye?"
        return _write_action_update(
            state, "reschedule", False, reply, clarification_needed=True,
            tool_outputs={**state["tool_outputs"], "last_availability": availability},
            pending_appointment_datetime=pending_dt_iso,
        )

    old_start = pending["start_datetime"]
    result = reschedule_calendar_tool.invoke({
        "event_id": pending["event_id"], "new_start_datetime_iso": new_dt.isoformat(),
    })
    if not result["success"]:
        reply = f"Maazrat sir, reschedule mein masla aa gaya: {result['error']}."
        return _write_action_update(state, "reschedule", False, reply, clarification_needed=False,
                                     pending_appointment_datetime=pending_dt_iso)

    when = new_dt.strftime("%A, %d %B %Y at %I:%M %p")
    reply = f"Ji bilkul, appointment ab {when} ke liye reschedule ho gayi hai."
    # _old_start_datetime is a transient hint for email_node only, stripped
    # back out once the email step reads it (see email_node below)
    new_status = {**pending, "start_datetime": new_dt.isoformat(), "status": "rescheduled",
                  "_old_start_datetime": old_start}
    crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "appointment_rescheduled",
                          "payload": {"event_id": pending["event_id"], "old_start": old_start,
                                      "new_start": new_dt.isoformat()}})
    crm_logger.log_appointment_history(
        state["session_id"], "rescheduled", client_phone=state["user_profile"].get("client_phone"),
        client_name=state["user_profile"].get("client_name"), property_id=pending.get("property_id"),
        property_title=pending.get("property_title"), start_datetime=new_dt.isoformat(),
        event_id=pending["event_id"],
    )
    return _write_action_update(state, "reschedule", True, reply, clarification_needed=False,
                                 appointment_status=new_status, pending_appointment_datetime=None)


# ---------- 7. Cancellation ----------

@traced_node("cancellation", annotate=lambda i, o: o.get("agent_reply", "")[:70])
def cancellation_node(state: AgentState) -> Dict[str, Any]:
    text = state["customer_text"]
    pending = state["appointment_status"]

    if not pending or not pending.get("event_id"):
        # this session hasn't booked anything yet, but the customer may be
        # calling back about an appointment from an earlier session
        pending = _find_appointment_by_phone(state["user_profile"].get("client_phone"))

    if not pending or not pending.get("event_id"):
        reply = "Maazrat sir, is call mein mujhe koi existing appointment nazar nahi aa rahi jise cancel karoon."
        return _write_action_update(state, "cancel", False, reply, clarification_needed=True)

    result = cancel_calendar_tool.invoke({"event_id": pending["event_id"], "reason": text})
    if not result["success"]:
        reply = f"Maazrat sir, cancel karne mein masla aa gaya: {result['error']}."
        return _write_action_update(state, "cancel", False, reply, clarification_needed=False)

    reply = "Ji theek hai, aap ki appointment cancel kar di gayi hai. Jab bhi ready hon, hum yahan hain."
    new_status = {**pending, "status": "cancelled", "_cancel_reason": text}
    crm_log_tool.invoke({"session_id": state["session_id"], "event_type": "appointment_cancelled",
                          "payload": {"event_id": pending["event_id"], "reason": text}})
    crm_logger.log_appointment_history(
        state["session_id"], "cancelled", client_phone=state["user_profile"].get("client_phone"),
        client_name=state["user_profile"].get("client_name"), property_id=pending.get("property_id"),
        property_title=pending.get("property_title"), start_datetime=pending.get("start_datetime"),
        event_id=pending["event_id"],
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


# ---------- 9. Goodbye ----------

@traced_node("goodbye", annotate=lambda i, o: "call closed")
def goodbye_node(state: AgentState) -> Dict[str, Any]:
    reply = "Shukriya sir, aap ka waqt dene ke liye. Allah Hafiz, aur zaroorat par hum yahan hain."
    return {"agent_reply": reply, "conversation_history": _say(state, reply)}
