"""
Day 4 - Task 4: Workflow Automation API

FastAPI wrapper around everything n8n needs to call to run:
    Call -> Intent -> Property Match -> Appointment -> Calendar -> Email -> CRM Update

Each pipeline stage is its own endpoint, matching the n8n workflow diagram
one node at a time — this is deliberate, not just a REST-ification of
run_turn(). n8n needs per-stage granularity to retry/branch on failure at
each step individually, which a single mega-endpoint can't give it.

Session model: an in-memory dict of session_id -> ConversationMemory,
mirroring one phone call each. This process is meant to run as a long-lived
service (uvicorn), not per-request — memory is lost on restart, which is
fine for a call in progress but means this is not yet suitable as a
production multi-instance deployment (would need Redis/Postgres-backed
sessions for that, out of scope here).

Run:
    pip install fastapi uvicorn
    uvicorn api:app --reload --port 8000

All endpoints return HTTP 200 with an explicit "success" boolean in the
body, even on failure — this is intentional, not an oversight. n8n's HTTP
Request node treats non-2xx as a hard node failure and its retry logic
works better against a stable 200-with-success-flag contract than against
mixed status codes, since a "the API call worked but the appointment
booking failed" case (which should be retried) looks identical over the
wire to "the API itself is down" (which should also be retried) either
way — n8n's IF node after each call branches on the success field, and
node-level retryOnFail handles transient failures before that IF is ever
reached. The one exception is malformed requests (missing session_id,
invalid JSON) — those return 4xx since retrying an invalid request is
pointless.
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from conversation_memory import ConversationMemory
from recommendation_engine import recommend_properties
from structured_retrieval import get_property_by_id
from objection_handler import detect_objection
from appointment_intent import detect_appointment_intent, parse_appointment_datetime
from call_intent import classify_call_intent
import calendar_integration as cal
import email_automation as mailer
from appointment_management import book_appointment, reschedule_appointment, cancel_appointment
import crm_logger

app = FastAPI(title="RealEstate Hub - Workflow Automation API", version="1.0")

_sessions: Dict[str, ConversationMemory] = {}


def _get_memory(session_id: str) -> ConversationMemory:
    if session_id not in _sessions:
        _sessions[session_id] = ConversationMemory()
    return _sessions[session_id]


def _require_session(session_id: str) -> ConversationMemory:
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    return _get_memory(session_id)


# ---------- Request/response models ----------

class CallStartRequest(BaseModel):
    session_id: str
    client_phone: Optional[str] = None


class TranscriptRequest(BaseModel):
    session_id: str
    customer_text: str


class PropertyMatchRequest(BaseModel):
    session_id: str


class AppointmentPrepareRequest(BaseModel):
    session_id: str
    customer_text: str  # used to parse date/time; property comes from last shown/mentioned
    property_id: Optional[int] = None
    employee_name: Optional[str] = None
    employee_email: Optional[str] = None
    meeting_notes: str = ""


class CalendarCreateRequest(BaseModel):
    session_id: str
    appointment: Dict[str, Any]  # serialized AppointmentDetails from /appointment/prepare


class CalendarRescheduleRequest(BaseModel):
    session_id: str
    event_id: str
    new_datetime_text: str


class CalendarCancelRequest(BaseModel):
    session_id: str
    event_id: str
    reason: str = ""


class EmailNotifyRequest(BaseModel):
    session_id: str
    kind: str  # "book" | "reschedule" | "cancel"
    appointment: Dict[str, Any]
    old_start_datetime: Optional[str] = None  # required for "reschedule"
    reason: str = ""  # used for "cancel"


class CRMLogRequest(BaseModel):
    session_id: str
    event_type: str
    status: str = "success"
    payload: Dict[str, Any] = {}


# ---------- Helpers ----------

def _appointment_details_to_dict(details: cal.AppointmentDetails) -> Dict[str, Any]:
    return {
        "client_name": details.client_name,
        "client_phone": details.client_phone,
        "property_title": details.property_title,
        "property_id": details.property_id,
        "start_datetime": details.start_datetime.isoformat(),
        "end_datetime": details.end_datetime.isoformat() if details.end_datetime else None,
        "employee_name": details.employee_name,
        "employee_email": details.employee_email,
        "meeting_notes": details.meeting_notes,
    }


def _dict_to_appointment_details(d: Dict[str, Any]) -> cal.AppointmentDetails:
    return cal.AppointmentDetails(
        client_name=d["client_name"],
        client_phone=d["client_phone"],
        property_title=d["property_title"],
        property_id=d.get("property_id"),
        start_datetime=datetime.fromisoformat(d["start_datetime"]),
        end_datetime=datetime.fromisoformat(d["end_datetime"]) if d.get("end_datetime") else None,
        employee_name=d.get("employee_name") or "RealEstate Hub Agent",
        employee_email=d.get("employee_email"),
        meeting_notes=d.get("meeting_notes", ""),
    )


# ---------- 1. Call ----------

@app.post("/webhook/call-start")
def call_start(req: CallStartRequest):
    """Starts (or resumes) a call session. First node in the n8n workflow,
    fired by the telephony trigger (Twilio webhook -> n8n -> here)."""
    memory = _get_memory(req.session_id)
    if req.client_phone:
        memory.slots.client_phone = req.client_phone

    crm_logger.log_event(req.session_id, "call_started", {"client_phone": req.client_phone})
    return {"success": True, "session_id": req.session_id}


# ---------- 2. Intent ----------

@app.post("/intent")
def intent(req: TranscriptRequest):
    """Classifies the call intent and updates memory slots from the
    transcript. n8n branches on call_intent to route toward the right
    downstream flow (matches the Day 1 flow diagrams)."""
    memory = _require_session(req.session_id)
    memory.add_turn("customer", req.customer_text)
    memory.update_from_customer_text(req.customer_text)

    result = {
        "success": True,
        "session_id": req.session_id,
        "call_intent": classify_call_intent(req.customer_text),
        "appointment_intent": detect_appointment_intent(req.customer_text),
        "objection": detect_objection(req.customer_text),
        "parsed_datetime": (
            parse_appointment_datetime(req.customer_text).isoformat()
            if parse_appointment_datetime(req.customer_text) else None
        ),
        "slots": {
            "budget": memory.slots.budget,
            "city": memory.slots.city,
            "area": memory.slots.area,
            "bedrooms": memory.slots.bedrooms,
            "purpose": memory.slots.purpose,
            "client_name": memory.slots.client_name,
            "client_phone": memory.slots.client_phone,
        },
    }
    crm_logger.log_event(req.session_id, "intent_detected", result)
    return result


# ---------- 3. Property Match ----------

@app.post("/property-match")
def property_match(req: PropertyMatchRequest):
    """Runs recommendation_engine against whatever slots are known so far.
    Empty results are reported honestly (success=True, candidates=[]) —
    n8n's downstream IF node decides whether to branch to "widen search"
    per the Day 1 flow diagrams (2.1-2.4 all have a no-match branch)."""
    memory = _require_session(req.session_id)
    candidates = recommend_properties(**memory.as_recommendation_kwargs(), top_n=3)
    if candidates:
        memory.record_shown_properties(candidates)

    result = {"success": True, "session_id": req.session_id, "candidates": candidates}
    crm_logger.log_event(
        req.session_id, "property_matched",
        {"count": len(candidates), "top_property_id": candidates[0]["id"] if candidates else None},
    )
    return result


# ---------- 4. Appointment (validation/prep, no side effects yet) ----------

@app.post("/appointment/prepare")
def appointment_prepare(req: AppointmentPrepareRequest):
    """Validates everything is present to book, and builds the
    AppointmentDetails payload the Calendar and Email stages need. Does
    NOT touch Calendar or Gmail — this is the "Appointment" node in the
    diagram, a pure validation/assembly step, kept separate so n8n can
    branch (ready vs missing-info) before any external API call happens."""
    memory = _require_session(req.session_id)

    property_info = get_property_by_id(req.property_id) if req.property_id else (
        memory.slots.last_shown_property_ids and get_property_by_id(memory.slots.last_shown_property_ids[0])
    )
    parsed_dt = parse_appointment_datetime(req.customer_text)

    missing = []
    if not memory.slots.client_name:
        missing.append("client_name")
    if not memory.slots.client_phone:
        missing.append("client_phone")
    if not property_info:
        missing.append("property")
    if not parsed_dt:
        missing.append("date_time")

    if missing:
        result = {"success": True, "ready": False, "missing": missing, "appointment": None}
        crm_logger.log_event(req.session_id, "appointment_prepare_incomplete", result, status="failed")
        return result

    details = cal.build_appointment_from_memory(
        memory, property_info, start_datetime=parsed_dt,
        employee_name=req.employee_name or "RealEstate Hub Agent",
        employee_email=req.employee_email,
    )
    if req.meeting_notes:
        details.meeting_notes = req.meeting_notes

    result = {"success": True, "ready": True, "missing": [], "appointment": _appointment_details_to_dict(details)}
    crm_logger.log_event(req.session_id, "appointment_prepared", result)
    return result


# ---------- 5. Calendar ----------

@app.post("/calendar/create")
def calendar_create(req: CalendarCreateRequest):
    memory = _require_session(req.session_id)
    details = _dict_to_appointment_details(req.appointment)

    cal_result = cal.create_appointment_event(details)
    if cal_result.success:
        memory.slots.pending_appointment = {
            "event_id": cal_result.event_id,
            "property_title": details.property_title,
            "property_id": details.property_id,
            "start_datetime": details.start_datetime,
            "employee_name": details.employee_name,
            "employee_email": details.employee_email,
            "status": "booked",
        }
        crm_logger.log_event(req.session_id, "appointment_booked",
                              {"event_id": cal_result.event_id, "html_link": cal_result.html_link})
        return {"success": True, "event_id": cal_result.event_id, "html_link": cal_result.html_link}

    crm_logger.log_event(req.session_id, "calendar_failed", {"error": cal_result.error}, status="failed")
    return {"success": False, "error": cal_result.error}


@app.post("/calendar/reschedule")
def calendar_reschedule(req: CalendarRescheduleRequest):
    memory = _require_session(req.session_id)
    parsed_dt = parse_appointment_datetime(req.new_datetime_text)
    if not parsed_dt:
        return {"success": False, "error": "Could not parse a new date/time from new_datetime_text"}

    old_start = memory.slots.pending_appointment.get("start_datetime") if memory.slots.pending_appointment else None
    cal_result = cal.reschedule_appointment_event(req.event_id, parsed_dt)

    if cal_result.success:
        if memory.slots.pending_appointment:
            memory.slots.pending_appointment["start_datetime"] = parsed_dt
            memory.slots.pending_appointment["status"] = "rescheduled"
        crm_logger.log_event(req.session_id, "appointment_rescheduled",
                              {"event_id": req.event_id, "old_start": str(old_start), "new_start": str(parsed_dt)})
        return {"success": True, "event_id": cal_result.event_id, "old_start_datetime": str(old_start),
                "new_start_datetime": parsed_dt.isoformat()}

    crm_logger.log_event(req.session_id, "calendar_failed", {"error": cal_result.error}, status="failed")
    return {"success": False, "error": cal_result.error}


@app.post("/calendar/cancel")
def calendar_cancel(req: CalendarCancelRequest):
    memory = _require_session(req.session_id)
    cal_result = cal.cancel_appointment_event(req.event_id, req.reason)

    if cal_result.success:
        if memory.slots.pending_appointment:
            memory.slots.pending_appointment["status"] = "cancelled"
        crm_logger.log_event(req.session_id, "appointment_cancelled",
                              {"event_id": req.event_id, "reason": req.reason})
        return {"success": True, "event_id": req.event_id}

    crm_logger.log_event(req.session_id, "calendar_failed", {"error": cal_result.error}, status="failed")
    return {"success": False, "error": cal_result.error}


# ---------- 6. Email ----------

@app.post("/email/notify")
def email_notify(req: EmailNotifyRequest):
    memory = _require_session(req.session_id)
    details = _dict_to_appointment_details(req.appointment)
    requirements_text = mailer.build_requirements_summary(memory)

    if req.kind == "book":
        email_result = mailer.send_appointment_notification(details, requirements_text)
    elif req.kind == "reschedule":
        if not req.old_start_datetime:
            return {"success": False, "error": "old_start_datetime is required for kind='reschedule'"}
        old_start = datetime.fromisoformat(req.old_start_datetime)
        email_result = mailer.send_reschedule_notification(details, old_start, requirements_text)
    elif req.kind == "cancel":
        email_result = mailer.send_cancellation_notification(details, req.reason)
    else:
        return {"success": False, "error": f"Unknown kind: {req.kind!r}, expected book/reschedule/cancel"}

    if email_result.success:
        crm_logger.log_event(req.session_id, "email_sent", {"kind": req.kind, "message_id": email_result.message_id})
        return {"success": True, "message_id": email_result.message_id}

    crm_logger.log_event(req.session_id, "email_failed", {"kind": req.kind, "error": email_result.error}, status="failed")
    return {"success": False, "error": email_result.error}


# ---------- 7. CRM Update ----------

@app.post("/crm/log")
def crm_log(req: CRMLogRequest):
    """Explicit CRM logging endpoint for n8n's final workflow node, and for
    logging workflow-level outcomes (e.g. 'workflow_completed',
    'workflow_failed_at_calendar') that don't map to one specific
    Python-side action above."""
    result = crm_logger.log_event(req.session_id, req.event_type, req.payload, req.status)
    if result.success:
        return {"success": True, "log_id": result.log_id}
    return {"success": False, "error": result.error}


@app.get("/crm/log/{session_id}")
def crm_log_get(session_id: str):
    """Full CRM trail for a session — handy for verifying the n8n workflow
    actually ran end to end without digging into the SQLite file directly."""
    return {"success": True, "session_id": session_id, "logs": crm_logger.get_logs_for_session(session_id)}


# ---------- Combined convenience endpoint (server-side chain, no n8n needed) ----------

@app.post("/workflow/run")
def workflow_run(req: TranscriptRequest):
    """Runs the entire Call -> Intent -> Property Match -> Appointment ->
    Calendar -> Email -> CRM Update chain in one call, server-side. This is
    NOT what n8n calls — n8n calls the granular endpoints above one at a
    time so it can retry/branch per step. This endpoint exists so the whole
    chain can be smoke-tested without n8n running at all, and mirrors
    exactly what the n8n workflow does step for step, so a mismatch between
    the two would be a bug worth catching."""
    session_id = req.session_id
    steps: List[Dict[str, Any]] = []

    intent_result = intent(TranscriptRequest(session_id=session_id, customer_text=req.customer_text))
    steps.append({"step": "intent", "result": intent_result})

    match_result = property_match(PropertyMatchRequest(session_id=session_id))
    steps.append({"step": "property_match", "result": match_result})

    if intent_result["appointment_intent"] != "book":
        crm_logger.log_event(session_id, "workflow_completed", {"reason": "no booking intent this turn"})
        return {"success": True, "steps": steps, "booked": False}

    prep_result = appointment_prepare(AppointmentPrepareRequest(session_id=session_id, customer_text=req.customer_text))
    steps.append({"step": "appointment_prepare", "result": prep_result})

    if not prep_result["ready"]:
        crm_logger.log_event(session_id, "workflow_failed_at_appointment_prepare",
                              {"missing": prep_result["missing"]}, status="failed")
        return {"success": True, "steps": steps, "booked": False}

    cal_result = calendar_create(CalendarCreateRequest(session_id=session_id, appointment=prep_result["appointment"]))
    steps.append({"step": "calendar_create", "result": cal_result})

    if not cal_result["success"]:
        crm_logger.log_event(session_id, "workflow_failed_at_calendar", cal_result, status="failed")
        return {"success": True, "steps": steps, "booked": False}

    email_result = email_notify(EmailNotifyRequest(
        session_id=session_id, kind="book", appointment=prep_result["appointment"]
    ))
    steps.append({"step": "email_notify", "result": email_result})

    crm_logger.log_event(session_id, "workflow_completed", {
        "booked": True, "event_id": cal_result["event_id"], "email_sent": email_result["success"],
    })
    return {"success": True, "steps": steps, "booked": True, "event_id": cal_result["event_id"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
