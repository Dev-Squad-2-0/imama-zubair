"""
Day 5 - Task 3: Tool Integration

Wraps the six required tool categories (Search Property, Calendar, Email,
CRM, Availability Checker, RAG Search) as langchain_core @tool functions,
so they're introspectable/bindable the same way regardless of whether a
node calls one directly (deterministic control flow - every node except
one) or an LLM chooses among them (the RAG node's tool-calling loop - see
nodes.py's module docstring for why that split is safety-motivated, not
incidental).

Every tool here is a thin wrapper around an already-proven Day 4 function -
no business logic is reimplemented. Arguments are plain JSON-friendly types
(ISO date strings, not datetime objects) since these get called both by
Python node code and, for rag_search_tool/property_lookup_tool, by an LLM
via generated JSON arguments.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

import calendar_integration as cal
import email_automation as mailer
import crm_logger
import recommendation_engine
import rag_pipeline
import structured_retrieval


# ---------- 1. Search Property ----------

@tool
def search_property_tool(budget: Optional[int] = None, city: Optional[str] = None,
                          area: Optional[str] = None, bedrooms: Optional[int] = None,
                          purpose: Optional[str] = None, top_n: int = 3) -> List[Dict[str, Any]]:
    """Searches properties matching budget/city/area/bedrooms/purpose, ranked
    by match score. Never returns a property that isn't currently available -
    structured_retrieval.search_properties() (which this calls into via
    recommendation_engine) filters on status="available" by default, and
    this tool does not override that filter."""
    return recommendation_engine.recommend_properties(
        budget=budget, city=city, area=area, bedrooms=bedrooms, purpose=purpose, top_n=top_n,
    )


# ---------- 2. Availability Checker ----------

@tool
def check_availability_tool(start_datetime_iso: str, duration_minutes: int = 30) -> Dict[str, Any]:
    """Checks whether the given start time (ISO 8601, e.g.
    "2026-08-20T15:00:00") is free on the company Google Calendar for
    duration_minutes. Returns {success, available, conflicting_events,
    error}. Fails closed: if the check itself can't complete (credentials/
    network problem), available is always False - never treat a failed
    check as "assume it's free"."""
    start_dt = datetime.fromisoformat(start_datetime_iso)
    result = cal.check_availability(start_dt, start_dt + timedelta(minutes=duration_minutes))
    return {
        "success": result.success, "available": result.available,
        "conflicting_events": result.conflicting_events, "error": result.error,
    }


# ---------- 3. Calendar (book / reschedule / cancel) ----------

@tool
def book_calendar_tool(client_name: str, client_phone: str, property_title: str,
                        start_datetime_iso: str, property_id: Optional[int] = None,
                        employee_name: str = "RealEstate Hub Agent",
                        employee_email: Optional[str] = None, meeting_notes: str = "") -> Dict[str, Any]:
    """Creates a real Google Calendar event for a property visit. Callers
    MUST call check_availability_tool for this exact slot first and only
    call this if it reported available=True - this tool does not re-check
    availability itself (same separation of concerns Day 4's
    appointment/prepare -> calendar/create split already used: validation
    and the side effect are different steps)."""
    details = cal.AppointmentDetails(
        client_name=client_name, client_phone=client_phone, property_title=property_title,
        property_id=property_id, start_datetime=datetime.fromisoformat(start_datetime_iso),
        employee_name=employee_name, employee_email=employee_email, meeting_notes=meeting_notes,
    )
    result = cal.create_appointment_event(details)
    return {"success": result.success, "event_id": result.event_id, "html_link": result.html_link, "error": result.error}


@tool
def reschedule_calendar_tool(event_id: str, new_start_datetime_iso: str) -> Dict[str, Any]:
    """Moves an existing event to a new start time. Same precondition as
    book_calendar_tool: callers must check_availability_tool the new slot
    first, this tool does not check it itself."""
    result = cal.reschedule_appointment_event(event_id, datetime.fromisoformat(new_start_datetime_iso))
    return {"success": result.success, "event_id": result.event_id, "html_link": result.html_link, "error": result.error}


@tool
def cancel_calendar_tool(event_id: str, reason: str = "") -> Dict[str, Any]:
    """Deletes an existing calendar event."""
    result = cal.cancel_appointment_event(event_id, reason)
    return {"success": result.success, "event_id": result.event_id, "error": result.error}


# ---------- 4. Email ----------

@tool
def email_tool(kind: str, client_name: str, client_phone: str, property_title: str,
                start_datetime_iso: str, property_id: Optional[int] = None,
                requirements_text: str = "", employee_name: str = "RealEstate Hub Agent",
                employee_email: Optional[str] = None, old_start_datetime_iso: Optional[str] = None,
                reason: str = "") -> Dict[str, Any]:
    """Sends the assigned employee an email notification. kind must be one
    of "book", "reschedule", "cancel" - same contract as Day 4's api.py
    /email/notify endpoint."""
    details = cal.AppointmentDetails(
        client_name=client_name, client_phone=client_phone, property_title=property_title,
        property_id=property_id, start_datetime=datetime.fromisoformat(start_datetime_iso),
        employee_name=employee_name, employee_email=employee_email,
    )
    if kind == "book":
        result = mailer.send_appointment_notification(details, requirements_text)
    elif kind == "reschedule":
        old_start = (
            datetime.fromisoformat(old_start_datetime_iso) if old_start_datetime_iso else details.start_datetime
        )
        result = mailer.send_reschedule_notification(details, old_start, requirements_text)
    elif kind == "cancel":
        result = mailer.send_cancellation_notification(details, reason)
    else:
        return {"success": False, "message_id": None, "error": f"Unknown kind: {kind!r}, expected book/reschedule/cancel"}
    return {"success": result.success, "message_id": result.message_id, "error": result.error}


# ---------- 5. CRM ----------

@tool
def crm_log_tool(session_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None,
                  status: str = "success") -> Dict[str, Any]:
    """Writes one CRM event row for this session (crm_events table) - the
    same log every Day 4 endpoint writes to, so Day 5 sessions show up in
    the same CRM trail Day 4's /crm/log/{session_id} already reads."""
    result = crm_logger.log_event(session_id, event_type, payload or {}, status)
    return {"success": result.success, "log_id": result.log_id, "error": result.error}


# ---------- 6. RAG Search ----------

@tool
def rag_search_tool(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Semantic search over property brochures, descriptions, and FAQs
    (ChromaDB). Returns the top_k most relevant chunks with their source
    and distance - use for factual questions that aren't a single exact
    field lookup (e.g. "what amenities does this have", "what's the
    cancellation policy"). For an exact field on a KNOWN property id
    (price, availability status, plot size, agent contact), prefer
    property_lookup_tool - it's a guaranteed-correct SQL row, not a
    similarity match."""
    collection = rag_pipeline.get_collection()
    hits = rag_pipeline.retrieve(collection, query, top_k=top_k)
    return [{"text": h["text"], "source": h["metadata"].get("source"), "distance": h["distance"]} for h in hits]


@tool
def property_lookup_tool(property_id: int) -> Dict[str, Any]:
    """Exact structured lookup for one property by id: price, availability
    status, plot size, agent name/phone. Use this instead of rag_search_tool
    whenever the property_id is already known and the question is an exact
    fact rather than something needing semantic search over free text."""
    p = structured_retrieval.get_property_by_id(property_id)
    if not p:
        return {"found": False}
    return {
        "found": True, "title": p.get("title"), "price_pkr": p.get("price_pkr"),
        "status": p.get("status"), "size_marla": p.get("size_marla"),
        "agent_name": p.get("agent_name"), "agent_phone": p.get("agent_phone"),
    }


if __name__ == "__main__":
    print(search_property_tool.invoke({"city": "Lahore", "area": "DHA Phase 6", "top_n": 2}))
