"""
Day 4 - Task 1: Google Calendar Integration

Creates real Google Calendar events for property visit appointments. This
is a standalone module, nothing from Day 3 is modified. It reads client
info straight out of ConversationMemory (client_name, client_phone, already
built in Day 3 for this exact purpose) and property info from
structured_retrieval.py (Day 2), so no new parsing/lookup logic is
duplicated here.

Auth: OAuth installed-app flow (matches a Desktop app OAuth client, not a
service account). GOOGLE_CREDENTIALS_PATH points at the OAuth client
secrets JSON downloaded from Google Cloud Console (APIs & Services ->
Credentials -> Desktop app). First run opens a browser for consent and
caches the resulting token next to it (token.json), so every run after
that is silent unless the token expires and can't be refreshed. Because
this is a real person's own calendar (not a service account), the calendar
to book into is normally "primary" — set GOOGLE_CALENDAR_ID="primary" in
.env unless you're deliberately targeting a different calendar you own.

Scope of this file (Day 4 Task 1 only): CREATE events. Availability
checking, rescheduling, and cancelling are separate Day 4 tasks and
deliberately not built here yet, so this stays a small reviewable unit.

Setup:
    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
"""

import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# httplib2 (used under the hood by the Google API client) resolves a
# connect()'s host a second time by name rather than reusing the address it
# already picked from getaddrinfo() - on a dual-stack machine with a flaky
# or tunneled IPv6 route (e.g. behind certain VPN adapters), that second
# lookup can land on an unreachable IPv6 address and hang for ~20s before
# timing out, even though IPv4 to the same host is instant. Forcing IPv4-only
# resolution process-wide sidesteps that entirely.
if not getattr(socket, "_ipv4_only_patched", False):
    _orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_only_getaddrinfo
    socket._ipv4_only_patched = True

from dotenv import find_dotenv

_DOTENV_PATH = find_dotenv()
load_dotenv(_DOTENV_PATH)


def _resolve_env_path(value: Optional[str]) -> Optional[str]:
    """.env stores GOOGLE_CREDENTIALS_PATH as a path relative to the
    project root ("credentials.json"). A bare relative path resolves
    against os.getcwd() by default, which silently breaks the moment this
    process is launched from any directory other than exactly the one
    whoever wrote .env happened to be in - a test script run from src/, a
    different way of starting uvicorn, etc. Anchoring it to the actual
    .env file's own directory instead makes it work no matter where the
    process is launched from."""
    if not value or os.path.isabs(value):
        return value
    anchor = os.path.dirname(_DOTENV_PATH) if _DOTENV_PATH else os.getcwd()
    return os.path.join(anchor, value)


GOOGLE_CREDENTIALS_PATH = _resolve_env_path(os.getenv("GOOGLE_CREDENTIALS_PATH"))
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
EMPLOYEE_EMAIL = os.getenv("EMPLOYEE_EMAIL")

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_DEFAULT_DURATION_MINUTES = 30
_DEFAULT_TIMEZONE = "Asia/Karachi"

# Token cache lives next to the OAuth client secrets file, e.g. if
# GOOGLE_CREDENTIALS_PATH is "credentials/oauth_client.json", the token is
# saved as "credentials/token.json". Created automatically after the first
# successful consent, reused (and refreshed) on every run after that.
_TOKEN_PATH = (
    os.path.join(os.path.dirname(GOOGLE_CREDENTIALS_PATH), "token.json")
    if GOOGLE_CREDENTIALS_PATH else None
)

_service = None  # lazy singleton, same pattern as rag_pipeline.py's _collection


def get_calendar_service():
    """Builds (or reuses) the Calendar API client via OAuth. Raises
    RuntimeError with an honest message rather than silently returning None
    if credentials are missing/invalid — a voice agent that "books" an
    appointment that never actually got created is worse than one that
    clearly fails.

    First run: opens a browser tab for the account owner to grant consent,
    then caches the token to _TOKEN_PATH. Later runs: loads the cached
    token and silently refreshes it if it expired. If the refresh token
    itself is invalid/revoked, re-runs the consent flow rather than
    crashing every future call."""
    global _service
    if _service is not None:
        return _service

    if not GOOGLE_CREDENTIALS_PATH:
        raise RuntimeError("GOOGLE_CREDENTIALS_PATH is not set in .env")
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        raise RuntimeError(f"OAuth client secrets file not found at {GOOGLE_CREDENTIALS_PATH}")
    if not GOOGLE_CALENDAR_ID:
        raise RuntimeError("GOOGLE_CALENDAR_ID is not set in .env (use \"primary\" for your own calendar)")

    creds = None
    if os.path.exists(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None  # refresh token invalid/revoked, fall through to re-consent

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_PATH, _SCOPES)
            creds = flow.run_local_server(port=0)

        with open(_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


@dataclass
class AppointmentDetails:
    """Everything the system_prompt.md APPOINTMENT BOOKING POLICY requires
    to be confirmed before finalizing a booking: client name, phone,
    employee, property, date, time. meeting_notes is free text (objection
    context, special requests, anything worth an agent knowing before the
    visit)."""
    client_name: str
    client_phone: str
    property_title: str
    property_id: Optional[int]
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    employee_name: str = "RealEstate Hub Agent"
    employee_email: Optional[str] = None
    meeting_notes: str = ""


@dataclass
class CalendarEventResult:
    success: bool
    event_id: Optional[str] = None
    html_link: Optional[str] = None
    error: Optional[str] = None


def _build_description(details: AppointmentDetails) -> str:
    return (
        f"Client Name: {details.client_name}\n"
        f"Client Phone: {details.client_phone}\n"
        f"Employee: {details.employee_name}\n"
        f"Property: {details.property_title}"
        + (f" (ID {details.property_id})" if details.property_id is not None else "")
        + f"\n\nMeeting Notes:\n{details.meeting_notes or 'None provided'}\n\n"
        "Booked automatically by RealEstate Hub voice agent."
    )


def create_appointment_event(details: AppointmentDetails) -> CalendarEventResult:
    """Creates the calendar event. Missing required fields are flagged
    honestly instead of silently booking an incomplete appointment, since
    system_prompt.md requires name, date, time, and property confirmed
    before finalizing."""
    missing = [
        field for field, value in [
            ("client_name", details.client_name),
            ("client_phone", details.client_phone),
            ("property_title", details.property_title),
            ("start_datetime", details.start_datetime),
        ] if not value
    ]
    if missing:
        return CalendarEventResult(
            success=False,
            error=f"Cannot book appointment, missing required field(s): {', '.join(missing)}",
        )

    end_dt = details.end_datetime or (
        details.start_datetime + timedelta(minutes=_DEFAULT_DURATION_MINUTES)
    )
    employee_email = details.employee_email or EMPLOYEE_EMAIL

    attendees = []
    if employee_email:
        attendees.append({"email": employee_email})

    event_body = {
        "summary": f"Property Visit: {details.client_name} - {details.property_title}",
        "description": _build_description(details),
        "start": {
            "dateTime": details.start_datetime.isoformat(),
            "timeZone": _DEFAULT_TIMEZONE,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": _DEFAULT_TIMEZONE,
        },
        "attendees": attendees,
        "reminders": {"useDefault": True},
    }

    try:
        service = get_calendar_service()
        event = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=event_body,
            sendUpdates="all" if attendees else "none",
        ).execute()
        return CalendarEventResult(
            success=True,
            event_id=event.get("id"),
            html_link=event.get("htmlLink"),
        )
    except HttpError as e:
        return CalendarEventResult(success=False, error=f"Google Calendar API error: {e}")
    except RuntimeError as e:
        # credentials/config problems from get_calendar_service()
        return CalendarEventResult(success=False, error=str(e))
    except Exception as e:
        return CalendarEventResult(success=False, error=f"Could not reach Google Calendar: {e}")


@dataclass
class AvailabilityResult:
    """success indicates whether the check itself completed (Calendar API
    reachable, credentials valid) - NOT whether the slot is free. available
    is the actual free/busy answer, only meaningful when success is True."""
    success: bool
    available: bool = False
    conflicting_events: list = field(default_factory=list)  # [{"start": ..., "end": ...}]
    error: Optional[str] = None


def check_availability(start_datetime: datetime, end_datetime: Optional[datetime] = None) -> AvailabilityResult:
    """Day 5 Task 4 ("never book unavailable slots") needs this checked
    BEFORE create_appointment_event()/reschedule_appointment_event() run -
    Day 4 never had it, create_appointment_event() booked unconditionally,
    so double-booking the same slot was possible there. Uses the Calendar
    API's freebusy.query, which is the correct primitive for "is this
    range free" (events.list would require paging + manually checking each
    event's time range for overlap).

    Fails CLOSED: if the check itself can't complete (credentials/network
    problem), this returns available=False, success=False rather than
    available=True - a booking node that can't confirm a slot is free must
    never treat that as "assume it's fine and book anyway"."""
    end_dt = end_datetime or (start_datetime + timedelta(minutes=_DEFAULT_DURATION_MINUTES))

    # Unlike events().insert() (which accepts a naive dateTime + a separate
    # timeZone field), freebusy.query requires timeMin/timeMax to already be
    # timezone-aware RFC3339 timestamps - a naive isoformat() 400s.
    tz = ZoneInfo(_DEFAULT_TIMEZONE)
    aware_start = start_datetime if start_datetime.tzinfo else start_datetime.replace(tzinfo=tz)
    aware_end = end_dt if end_dt.tzinfo else end_dt.replace(tzinfo=tz)

    try:
        service = get_calendar_service()
        body = {
            "timeMin": aware_start.isoformat(),
            "timeMax": aware_end.isoformat(),
            "items": [{"id": GOOGLE_CALENDAR_ID}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_periods = result.get("calendars", {}).get(GOOGLE_CALENDAR_ID, {}).get("busy", [])
        return AvailabilityResult(
            success=True,
            available=not busy_periods,
            conflicting_events=[{"start": b["start"], "end": b["end"]} for b in busy_periods],
        )
    except HttpError as e:
        return AvailabilityResult(success=False, available=False, error=f"Google Calendar API error: {e}")
    except RuntimeError as e:
        return AvailabilityResult(success=False, available=False, error=str(e))
    except Exception as e:
        return AvailabilityResult(success=False, available=False, error=f"Could not reach Google Calendar: {e}")


def reschedule_appointment_event(event_id: str, new_start_datetime: datetime,
                                  new_end_datetime: Optional[datetime] = None) -> CalendarEventResult:
    """Moves an existing event to a new time. Fetches the event first so
    everything else (attendees, description, summary) is left untouched —
    system_prompt.md's policy is "confirm the original appointment details
    before changing anything", this is the part of that which is Claude's
    to enforce in code: only start/end change, nothing else gets
    overwritten by accident."""
    if not event_id:
        return CalendarEventResult(success=False, error="event_id is required to reschedule")
    if not new_start_datetime:
        return CalendarEventResult(success=False, error="new_start_datetime is required to reschedule")

    try:
        service = get_calendar_service()
        existing = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
    except HttpError as e:
        return CalendarEventResult(success=False, error=f"Could not find existing appointment: {e}")
    except RuntimeError as e:
        return CalendarEventResult(success=False, error=str(e))
    except Exception as e:
        return CalendarEventResult(success=False, error=f"Could not reach Google Calendar: {e}")

    # keep original duration if no new end time given
    try:
        old_start = datetime.fromisoformat(existing["start"]["dateTime"])
        old_end = datetime.fromisoformat(existing["end"]["dateTime"])
        original_duration = old_end - old_start
    except (KeyError, ValueError):
        original_duration = timedelta(minutes=_DEFAULT_DURATION_MINUTES)

    new_end = new_end_datetime or (new_start_datetime + original_duration)

    existing["start"] = {"dateTime": new_start_datetime.isoformat(), "timeZone": _DEFAULT_TIMEZONE}
    existing["end"] = {"dateTime": new_end.isoformat(), "timeZone": _DEFAULT_TIMEZONE}

    try:
        updated = service.events().update(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=existing, sendUpdates="all"
        ).execute()
        return CalendarEventResult(success=True, event_id=updated.get("id"), html_link=updated.get("htmlLink"))
    except HttpError as e:
        return CalendarEventResult(success=False, error=f"Google Calendar API error: {e}")
    except Exception as e:
        return CalendarEventResult(success=False, error=f"Could not reach Google Calendar: {e}")


def cancel_appointment_event(event_id: str, reason: str = "") -> CalendarEventResult:
    """Cancels (deletes) an existing appointment. system_prompt.md: "confirm
    which appointment is being cancelled ... before finalizing" — that
    confirmation is a conversation-layer responsibility (conversation_agent.py
    /  the LLM turn), this function just does the actual deletion once a
    specific event_id has already been confirmed. reason is accepted for
    logging/CRM purposes even though the Calendar API itself has no
    "cancellation reason" field."""
    if not event_id:
        return CalendarEventResult(success=False, error="event_id is required to cancel")

    try:
        service = get_calendar_service()
        service.events().delete(
            calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, sendUpdates="all"
        ).execute()
        return CalendarEventResult(success=True, event_id=event_id)
    except HttpError as e:
        return CalendarEventResult(success=False, error=f"Google Calendar API error: {e}")
    except RuntimeError as e:
        return CalendarEventResult(success=False, error=str(e))
    except Exception as e:
        return CalendarEventResult(success=False, error=f"Could not reach Google Calendar: {e}")


def build_appointment_from_memory(memory, property_info: dict, start_datetime: datetime,
                                   end_datetime: Optional[datetime] = None,
                                   employee_name: str = "RealEstate Hub Agent",
                                   employee_email: Optional[str] = None,
                                   meeting_notes: str = "") -> AppointmentDetails:
    """Convenience constructor so conversation_agent.py doesn't have to
    manually pull fields out of ConversationMemory.slots and a property
    dict from structured_retrieval.py — it just passes both objects
    straight in. Kept separate from AppointmentDetails itself so this file
    has no import-time dependency on conversation_memory.py (only needs it
    at call time, duck-typed on .slots)."""
    return AppointmentDetails(
        client_name=memory.slots.client_name or "Unknown",
        client_phone=memory.slots.client_phone or "Not provided",
        property_title=property_info.get("title", "Unknown property") if property_info else "Unknown property",
        property_id=property_info.get("id") if property_info else None,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        employee_name=employee_name,
        employee_email=employee_email,
        meeting_notes=meeting_notes,
    )


if __name__ == "__main__":
    # Manual smoke test. Needs real credentials in .env to actually hit the
    # API — otherwise this will print an honest failure, not a fake success.
    sample = AppointmentDetails(
        client_name="Ahmed Khan",
        client_phone="0300-1234567",
        property_title="10 Marla Corner House - DHA Phase 6",
        property_id=101,
        start_datetime=datetime.now() + timedelta(days=1, hours=2),
        employee_name="Bilal (Sales Executive)",
        meeting_notes="Client asked about price trend in DHA Phase 6 before agreeing to visit.",
    )

    result = create_appointment_event(sample)
    if result.success:
        print(f"Event created: {result.event_id}")
        print(f"Link: {result.html_link}")
    else:
        print(f"Failed to create event: {result.error}")
