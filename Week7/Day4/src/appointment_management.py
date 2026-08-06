"""
Day 4 - Task 3: Appointment Management

Three operations — book, reschedule, cancel — each of which touches BOTH
Calendar (calendar_integration.py) and email (email_automation.py) as one
unit. This is the module conversation_agent.py should actually call; it
should not call calendar_integration.py / email_automation.py directly for
these three actions, so the two side effects never drift out of sync (e.g.
a reschedule that updates the calendar but forgets to email the employee).

Also updates ConversationMemory.slots.pending_appointment so a later turn
in the same call ("actually can we move it to Friday instead") has the
event_id and current time to work with, without the customer having to
repeat property/date/employee.

system_prompt.md's APPOINTMENT BOOKING POLICY is enforced at this layer,
not duplicated inside calendar_integration.py:
    - "Always confirm customer name, date, time, and property before
      finalizing a booking" -> AppointmentDetails' required fields already
      cover this (calendar_integration.create_appointment_event() refuses
      to book if any are missing); book_appointment() does not add a second
      confirmation step, that confirmation happens in the LLM conversation
      turn before this function is ever called.
    - "For rescheduling, always confirm the original appointment details
      before changing anything" -> reschedule_appointment() fetches and
      returns the OLD time as part of its result specifically so the
      calling code/LLM can read it back to the customer.
    - "For cancellations, confirm which appointment is being cancelled" ->
      cancel_appointment() requires an explicit event_id, it will not guess
      which appointment from a bare customer name.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import calendar_integration as cal
import email_automation as mailer


@dataclass
class AppointmentActionResult:
    """Unified result for all three operations, so conversation_agent.py
    has one shape to check regardless of which action ran."""
    success: bool
    action: str                      # "booked", "rescheduled", "cancelled"
    event_id: Optional[str] = None
    html_link: Optional[str] = None
    old_start_datetime: Optional[datetime] = None   # populated on reschedule
    calendar_error: Optional[str] = None
    email_sent: bool = False
    email_error: Optional[str] = None

    @property
    def fully_succeeded(self) -> bool:
        """True only if both the calendar side and the email side worked.
        A calendar-only partial success is still reported (success=True,
        email_sent=False) rather than rolled back — the appointment is real
        either way, the employee just needs a manual heads-up if the email
        leg failed."""
        return self.success and self.email_sent


def _update_pending_appointment_slot(memory, details: cal.AppointmentDetails,
                                      event_id: Optional[str], status: str):
    """Keeps ConversationMemory.slots.pending_appointment in sync so a
    follow-up turn ("move it an hour later") has what it needs. Stored as a
    plain dict since ConversationSlots.pending_appointment is already typed
    Optional[Dict[str, Any]] in conversation_memory.py — no changes needed
    there."""
    memory.slots.pending_appointment = {
        "event_id": event_id,
        "property_title": details.property_title,
        "property_id": details.property_id,
        "start_datetime": details.start_datetime,
        "employee_name": details.employee_name,
        "employee_email": details.employee_email,
        "status": status,  # "booked" | "rescheduled" | "cancelled"
    }


def book_appointment(memory, details: cal.AppointmentDetails) -> AppointmentActionResult:
    """Creates the calendar event, then emails the employee. Requirements
    text for the email is derived from memory automatically so callers
    don't have to build it separately."""
    cal_result = cal.create_appointment_event(details)
    if not cal_result.success:
        return AppointmentActionResult(
            success=False, action="booked", calendar_error=cal_result.error
        )

    requirements_text = mailer.build_requirements_summary(memory)
    email_result = mailer.send_appointment_notification(details, requirements_text)

    _update_pending_appointment_slot(memory, details, cal_result.event_id, "booked")

    return AppointmentActionResult(
        success=True,
        action="booked",
        event_id=cal_result.event_id,
        html_link=cal_result.html_link,
        email_sent=email_result.success,
        email_error=None if email_result.success else email_result.error,
    )


def reschedule_appointment(memory, event_id: str, new_start_datetime: datetime,
                            details: cal.AppointmentDetails,
                            new_end_datetime: Optional[datetime] = None) -> AppointmentActionResult:
    """Moves an existing booking to a new time and emails the employee with
    both the old and new time. `details` should describe the appointment as
    it will be AFTER the change (client/property/employee stay the same,
    only start_datetime differs) — old_start_datetime for the email comes
    from what the calendar event actually had stored, not from memory, so
    the "previous time" in the notification is always accurate even if
    memory drifted."""
    old_start = memory.slots.pending_appointment.get("start_datetime") if memory.slots.pending_appointment else None

    cal_result = cal.reschedule_appointment_event(event_id, new_start_datetime, new_end_datetime)
    if not cal_result.success:
        return AppointmentActionResult(
            success=False, action="rescheduled", calendar_error=cal_result.error
        )

    updated_details = cal.AppointmentDetails(
        client_name=details.client_name,
        client_phone=details.client_phone,
        property_title=details.property_title,
        property_id=details.property_id,
        start_datetime=new_start_datetime,
        end_datetime=new_end_datetime,
        employee_name=details.employee_name,
        employee_email=details.employee_email,
        meeting_notes=details.meeting_notes,
    )

    requirements_text = mailer.build_requirements_summary(memory)
    email_result = mailer.send_reschedule_notification(
        updated_details, old_start or new_start_datetime, requirements_text
    )

    _update_pending_appointment_slot(memory, updated_details, cal_result.event_id, "rescheduled")

    return AppointmentActionResult(
        success=True,
        action="rescheduled",
        event_id=cal_result.event_id,
        html_link=cal_result.html_link,
        old_start_datetime=old_start,
        email_sent=email_result.success,
        email_error=None if email_result.success else email_result.error,
    )


def cancel_appointment(memory, event_id: str, details: cal.AppointmentDetails,
                        reason: str = "") -> AppointmentActionResult:
    """Deletes the calendar event and emails the employee with the reason
    (if the customer gave one). event_id must be explicit — this
    deliberately will not guess "the customer's most recent appointment"
    from name alone, matching system_prompt.md's cancellation policy."""
    cal_result = cal.cancel_appointment_event(event_id, reason)
    if not cal_result.success:
        return AppointmentActionResult(
            success=False, action="cancelled", calendar_error=cal_result.error
        )

    email_result = mailer.send_cancellation_notification(details, reason)

    _update_pending_appointment_slot(memory, details, event_id, "cancelled")

    return AppointmentActionResult(
        success=True,
        action="cancelled",
        event_id=event_id,
        email_sent=email_result.success,
        email_error=None if email_result.success else email_result.error,
    )


if __name__ == "__main__":
    # Manual smoke test walking through book -> reschedule -> cancel on one
    # appointment. Needs real Calendar + Gmail OAuth consent to actually
    # hit the APIs, otherwise each step prints an honest failure.
    from datetime import timedelta
    from conversation_memory import ConversationMemory

    memory = ConversationMemory()
    memory.slots.budget = 30_000_000
    memory.slots.city = "Lahore"
    memory.slots.area = "DHA Phase 6"
    memory.slots.purpose = "buy"

    details = cal.AppointmentDetails(
        client_name="Ahmed Khan",
        client_phone="0300-1234567",
        property_title="10 Marla Corner House - DHA Phase 6",
        property_id=101,
        start_datetime=datetime.now() + timedelta(days=1, hours=2),
        employee_name="Bilal (Sales Executive)",
        meeting_notes="First visit, interested after price trend discussion.",
    )

    print("-- Booking --")
    booked = book_appointment(memory, details)
    print(booked)

    if booked.success and booked.event_id:
        print("\n-- Rescheduling --")
        new_time = details.start_datetime + timedelta(days=1)
        rescheduled = reschedule_appointment(memory, booked.event_id, new_time, details)
        print(rescheduled)

        print("\n-- Cancelling --")
        cancelled = cancel_appointment(
            memory, booked.event_id, details, reason="Client asked to cancel, will rebook later."
        )
        print(cancelled)
