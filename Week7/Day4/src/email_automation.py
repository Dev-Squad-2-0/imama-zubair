"""
Day 4 - Task 2: Email Automation

Sends the assigned employee an email notification when an appointment gets
booked, with meeting time, property, client details, and the customer's
stated requirements (budget/city/area/bedrooms/purpose, straight out of
ConversationMemory.slots).

Deliberately reuses calendar_integration.py's AppointmentDetails instead of
defining its own client/property/time fields


Setup:
    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
"""

import base64
import os
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Optional

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from calendar_integration import AppointmentDetails, EMPLOYEE_EMAIL, GOOGLE_CREDENTIALS_PATH

load_dotenv()

_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

_TOKEN_PATH = (
    os.path.join(os.path.dirname(GOOGLE_CREDENTIALS_PATH), "gmail_token.json")
    if GOOGLE_CREDENTIALS_PATH else None
)

_service = None  # lazy singleton, same pattern as calendar_integration.py's _service


def get_gmail_service():
    """Builds (or reuses) the Gmail API client via OAuth. Same flow shape as
    calendar_integration.get_calendar_service() — first run opens a browser
    for consent, caches the token, refreshes silently after that. Raises
    RuntimeError on missing/broken config rather than pretending an email
    went out."""
    global _service
    if _service is not None:
        return _service

    if not GOOGLE_CREDENTIALS_PATH:
        raise RuntimeError("GOOGLE_CREDENTIALS_PATH is not set in .env")
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        raise RuntimeError(f"OAuth client secrets file not found at {GOOGLE_CREDENTIALS_PATH}")

    creds = None
    if os.path.exists(_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_PATH, _SCOPES)
            creds = flow.run_local_server(port=0)

        with open(_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    _service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return _service


@dataclass
class EmailResult:
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


def build_requirements_summary(memory) -> str:
    """Turns ConversationMemory.slots into the plain-text requirements
    block for the email. Only includes fields that are actually filled in —
    an email full of "Bedrooms: None" lines is worse than a shorter honest
    one. Takes the memory object directly (duck-typed on .slots) so this
    file doesn't need to import conversation_memory.py just for this."""
    slots = memory.slots
    lines = []
    if slots.budget:
        lines.append(f"Budget: PKR {slots.budget:,}")
    if slots.city:
        lines.append(f"City: {slots.city}")
    if slots.area:
        lines.append(f"Area: {slots.area}")
    if slots.bedrooms:
        lines.append(f"Bedrooms: {slots.bedrooms}")
    if slots.purpose:
        lines.append(f"Purpose: {slots.purpose}")
    if slots.property_type:
        lines.append(f"Property type: {slots.property_type}")
    return "\n".join(lines) if lines else "No specific requirements captured on the call."


def _build_email_body(details: AppointmentDetails, requirements_text: str) -> str:
    return (
        f"New appointment booked via the RealEstate Hub voice agent.\n\n"
        f"Meeting Time: {details.start_datetime.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        f"Property: {details.property_title}"
        + (f" (ID {details.property_id})" if details.property_id is not None else "")
        + "\n\n"
        f"Client Details:\n"
        f"  Name: {details.client_name}\n"
        f"  Phone: {details.client_phone}\n\n"
        f"Client Requirements:\n{requirements_text}\n\n"
        f"Meeting Notes:\n{details.meeting_notes or 'None provided'}\n\n"
        f"This is an automated notification, no reply needed."
    )


def send_appointment_notification(details: AppointmentDetails, requirements_text: str,
                                   to_email: Optional[str] = None) -> EmailResult:
    """Sends the assigned employee an email with meeting time, property,
    client details, and requirements. to_email defaults to
    details.employee_email, falling back to EMPLOYEE_EMAIL from .env —
    same fallback order calendar_integration.create_appointment_event()
    uses for the calendar invite, so the two stay consistent about who's
    considered "the assigned employee" for a given booking."""
    recipient = to_email or details.employee_email or EMPLOYEE_EMAIL

    if not recipient:
        return EmailResult(
            success=False,
            error="No employee email available (not passed in, not set on details, "
                  "and EMPLOYEE_EMAIL is not set in .env)",
        )

    body = _build_email_body(details, requirements_text)
    message = MIMEText(body)
    message["to"] = recipient
    message["subject"] = f"New Appointment: {details.client_name} - {details.property_title}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        service = get_gmail_service()
        sent = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return EmailResult(success=True, message_id=sent.get("id"))
    except HttpError as e:
        return EmailResult(success=False, error=f"Gmail API error: {e}")
    except RuntimeError as e:
        return EmailResult(success=False, error=str(e))


def _build_reschedule_body(details: AppointmentDetails, old_start, requirements_text: str) -> str:
    return (
        f"Appointment rescheduled via the RealEstate Hub voice agent.\n\n"
        f"Previous Meeting Time: {old_start.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        f"New Meeting Time: {details.start_datetime.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        f"Property: {details.property_title}"
        + (f" (ID {details.property_id})" if details.property_id is not None else "")
        + "\n\n"
        f"Client Details:\n"
        f"  Name: {details.client_name}\n"
        f"  Phone: {details.client_phone}\n\n"
        f"Client Requirements:\n{requirements_text}\n\n"
        f"This is an automated notification, no reply needed."
    )


def send_reschedule_notification(details: AppointmentDetails, old_start_datetime,
                                  requirements_text: str, to_email: Optional[str] = None) -> EmailResult:
    """Notifies the employee an appointment moved to a new time. details.start_datetime
    should already hold the NEW time (same object create_appointment_event()/
    reschedule_appointment_event() used), old_start_datetime is passed in
    separately so the email can show both."""
    recipient = to_email or details.employee_email or EMPLOYEE_EMAIL
    if not recipient:
        return EmailResult(
            success=False,
            error="No employee email available (not passed in, not set on details, "
                  "and EMPLOYEE_EMAIL is not set in .env)",
        )

    body = _build_reschedule_body(details, old_start_datetime, requirements_text)
    message = MIMEText(body)
    message["to"] = recipient
    message["subject"] = f"Appointment Rescheduled: {details.client_name} - {details.property_title}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        service = get_gmail_service()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return EmailResult(success=True, message_id=sent.get("id"))
    except HttpError as e:
        return EmailResult(success=False, error=f"Gmail API error: {e}")
    except RuntimeError as e:
        return EmailResult(success=False, error=str(e))


def _build_cancellation_body(details: AppointmentDetails, reason: str) -> str:
    return (
        f"Appointment cancelled via the RealEstate Hub voice agent.\n\n"
        f"Cancelled Meeting Time: {details.start_datetime.strftime('%A, %d %B %Y at %I:%M %p')}\n"
        f"Property: {details.property_title}"
        + (f" (ID {details.property_id})" if details.property_id is not None else "")
        + "\n\n"
        f"Client Details:\n"
        f"  Name: {details.client_name}\n"
        f"  Phone: {details.client_phone}\n\n"
        f"Reason: {reason or 'Not provided'}\n\n"
        f"This is an automated notification, no reply needed."
    )


def send_cancellation_notification(details: AppointmentDetails, reason: str = "",
                                    to_email: Optional[str] = None) -> EmailResult:
    """Notifies the employee an appointment was cancelled, with the reason
    if the customer gave one (matches cancel_appointment_event()'s optional
    reason param in calendar_integration.py)."""
    recipient = to_email or details.employee_email or EMPLOYEE_EMAIL
    if not recipient:
        return EmailResult(
            success=False,
            error="No employee email available (not passed in, not set on details, "
                  "and EMPLOYEE_EMAIL is not set in .env)",
        )

    body = _build_cancellation_body(details, reason)
    message = MIMEText(body)
    message["to"] = recipient
    message["subject"] = f"Appointment Cancelled: {details.client_name} - {details.property_title}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        service = get_gmail_service()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return EmailResult(success=True, message_id=sent.get("id"))
    except HttpError as e:
        return EmailResult(success=False, error=f"Gmail API error: {e}")
    except RuntimeError as e:
        return EmailResult(success=False, error=str(e))


if __name__ == "__main__":
    # Manual smoke test. Needs real OAuth consent + EMPLOYEE_EMAIL in .env
    # to actually send — otherwise prints an honest failure, not a fake
    # success.
    from datetime import datetime, timedelta

    sample = AppointmentDetails(
        client_name="Ahmed Khan",
        client_phone="0300-1234567",
        property_title="10 Marla Corner House - DHA Phase 6",
        property_id=101,
        start_datetime=datetime.now() + timedelta(days=1, hours=2),
        employee_name="Bilal (Sales Executive)",
        meeting_notes="Client asked about price trend in DHA Phase 6 before agreeing to visit.",
    )
    sample_requirements = (
        "Budget: PKR 30,000,000\n"
        "City: Lahore\n"
        "Area: DHA Phase 6\n"
        "Purpose: buy"
    )

    result = send_appointment_notification(sample, sample_requirements)
    if result.success:
        print(f"Email sent: {result.message_id}")
    else:
        print(f"Failed to send email: {result.error}")