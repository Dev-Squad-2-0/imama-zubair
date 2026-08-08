"""
Day 5 - Task 1: LangGraph State Design

AgentState is the single object every node reads and partially updates as
it moves through the graph. Shape follows the brief's field list exactly
(conversation history, user profile, property preferences, budget, intent,
tool outputs, appointment status) plus two bookkeeping fields Task 5's
logging needs (turn_id, node_trace) and two Task 4 validation needs
(missing_fields, clarification_needed).

Slot-parsing itself is NOT reimplemented here - conversation_memory.py's
ConversationMemory.update_from_customer_text() (name/phone/budget/area/
city/purpose/bedrooms extraction, already proven in Day 3/4) is reused as-is
via _slots_from_text(); this module only reshapes those slots into
AgentState's nested dict layout.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conversation_memory import ConversationMemory


class AgentState(TypedDict, total=False):
    session_id: str
    turn_id: int

    caller_id: Optional[str]                            # phone number from the TELEPHONY layer itself (e.g.
                                                          # Twilio's "From" field) - NOT parsed from speech, so it's
                                                          # available even if the customer never says a number out
                                                          # loud, or STT mangles the digits. Not wired to a real
                                                          # telephony provider yet (see voice_pipeline.py's
                                                          # telephony_send_audio() docstring - same "not implemented,
                                                          # here's exactly where it plugs in" status). Set via
                                                          # graph.run_turn(..., caller_id=...); None for the current
                                                          # mic-based live_voice_pipeline.py, which has no caller ID
                                                          # source at all (it isn't a phone call).

    conversation_history: List[Dict[str, str]]        # [{"speaker": "customer"|"agent", "text": ...}]
    user_profile: Dict[str, Any]                        # client_name, client_phone
    property_preferences: Dict[str, Any]                # budget, city, area, bedrooms, purpose, property_type,
                                                          # last_shown_property_ids, last_shown_min_price/max_price
    intent: Dict[str, Any]                              # call_intent, appointment_intent, objection
    tool_outputs: Dict[str, Any]                        # last_recommendations, last_rag_hits, last_availability
    appointment_status: Optional[Dict[str, Any]]        # event_id, status, start_datetime, property_title, ...

    customer_text: str                                  # this turn's raw input
    agent_reply: str                                    # this turn's output, filled in by whichever node replies
    decline_count: int                                  # "no thanks" count, for the stop-pushing-after-2 rule

    missing_fields: List[str]                           # Task 4: what's still needed before a write action
    clarification_needed: bool

    node_trace: List[str]                               # nodes visited this turn (graph_logger fills this in)


def new_agent_state(session_id: str) -> AgentState:
    return AgentState(
        session_id=session_id,
        turn_id=0,
        caller_id=None,
        conversation_history=[],
        user_profile={"client_name": None, "client_phone": None},
        property_preferences={
            "budget": None, "city": None, "area": None, "bedrooms": None,
            "purpose": None, "property_type": None,
            "last_shown_property_ids": [], "last_shown_min_price": None, "last_shown_max_price": None,
        },
        intent={"call_intent": None, "appointment_intent": None, "objection": None},
        tool_outputs={},
        appointment_status=None,
        customer_text="",
        agent_reply="",
        decline_count=0,
        missing_fields=[],
        clarification_needed=False,
        node_trace=[],
    )


def slots_from_text(existing_profile: Dict[str, Any], existing_prefs: Dict[str, Any],
                     existing_decline_count: int, customer_text: str) -> Dict[str, Any]:
    """Runs Day 3/4's proven ConversationMemory.update_from_customer_text()
    against a throwaway memory pre-seeded with the current state, then
    reshapes the result back into AgentState's {user_profile,
    property_preferences, decline_count} layout. Reused rather than
    reimplemented so Day 5's slot-filling never drifts from Day 4's."""
    memory = ConversationMemory()
    memory.slots.client_name = existing_profile.get("client_name")
    memory.slots.client_phone = existing_profile.get("client_phone")
    memory.slots.budget = existing_prefs.get("budget")
    memory.slots.city = existing_prefs.get("city")
    memory.slots.area = existing_prefs.get("area")
    memory.slots.bedrooms = existing_prefs.get("bedrooms")
    memory.slots.purpose = existing_prefs.get("purpose")
    memory.slots.property_type = existing_prefs.get("property_type")
    memory.slots.decline_count = existing_decline_count

    memory.update_from_customer_text(customer_text)

    return {
        "user_profile": {
            "client_name": memory.slots.client_name,
            "client_phone": memory.slots.client_phone,
        },
        "property_preferences": {
            **existing_prefs,
            "budget": memory.slots.budget,
            "city": memory.slots.city,
            "area": memory.slots.area,
            "bedrooms": memory.slots.bedrooms,
            "purpose": memory.slots.purpose,
            "property_type": memory.slots.property_type,
        },
        "decline_count": memory.slots.decline_count,
    }


class SessionStore:
    """In-memory session_id -> AgentState store, same lifetime/limitations
    as api.py's _sessions dict in Day 4 (lost on process restart - fine for
    a call in progress, not yet a multi-instance-safe production store)."""

    def __init__(self):
        self._sessions: Dict[str, AgentState] = {}

    def get_or_create(self, session_id: str) -> AgentState:
        if session_id not in self._sessions:
            self._sessions[session_id] = new_agent_state(session_id)
        return self._sessions[session_id]

    def save(self, state: AgentState) -> None:
        self._sessions[state["session_id"]] = state

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


if __name__ == "__main__":
    store = SessionStore()
    s = store.get_or_create("smoke-test")
    print("Fresh state:", s)

    updates = slots_from_text(s["user_profile"], s["property_preferences"], s["decline_count"],
                               "Mera naam Ahmed hai, budget 3 crore hai, DHA Phase 6 mein chahiye.")
    print("\nSlot updates from text:", updates)