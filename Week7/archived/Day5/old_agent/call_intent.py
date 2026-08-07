"""
Day 4 - call intent classification.

api.py's /intent endpoint needs to tell n8n which of the Day 1 Task 2
conversation flows this call belongs to (buyer / rental / commercial /
investment / returning customer / appointment rescheduling / appointment
cancellation), so n8n's IF/Switch node can branch the workflow the same
way the flowcharts describe. This is a separate, smaller concern from
appointment_intent.py's job (book/reschedule/cancel an appointment) — a
call can be a "rental inquiry" for several turns before any appointment
intent ever comes up, and this module is what tells n8n that from turn one.

Same keyword-classification pattern as objection_handler.py and
appointment_intent.py, deliberately not an LLM call: n8n needs this fast
and deterministic since it's used purely for routing, not for anything the
customer hears.

Precedence, checked in this order:
    1. cancel / reschedule (appointment_intent.py's categories) — these
       override everything else, a customer trying to cancel doesn't want
       to be routed back into a fresh property inquiry flow.
    2. returning_customer — an explicit self-reference to a prior
       call/visit, which changes the greeting/flow per the Day 1 diagram
       ("Returning customer" flow) regardless of what they ask about next.
    3. investment / commercial / rental — checked before the generic
       "buyer" fallback since their keywords are more specific.
    4. buyer_inquiry — the default once purpose looks like a purchase, or
       there's simply not enough signal yet (most calls start here).
"""

from typing import Optional

import appointment_intent as appt


CALL_INTENTS = [
    "buyer_inquiry",
    "rental_inquiry",
    "commercial_inquiry",
    "investment_inquiry",
    "returning_customer",
    "appointment_rescheduling",
    "appointment_cancellation",
]

_RETURNING_KEYWORDS = [
    "pehle bhi baat", "pehle bhi call", "maine pehle call kiya", "dobara call",
    "mera pehle se", "i called before", "i spoke to", "pehle visit kiya tha",
    "already talked to", "returning customer", "dubara contact", "pichli baar",
]

_RENTAL_KEYWORDS = [
    "rent", "kiraya", "kiraye", "rent par", "rent pe", "lease",
]

_COMMERCIAL_KEYWORDS = [
    "commercial", "shop", "dukan", "office space", "plaza", "showroom",
    "warehouse", "godown",
]

_INVESTMENT_KEYWORDS = [
    "invest", "investment", "return", "profit", "resale", "rental yield",
    "capital gain", "munafa",
]


def classify_call_intent(customer_text: str) -> str:
    """Returns one of CALL_INTENTS. Never returns None — falls back to
    "buyer_inquiry" so n8n's Switch node always has a valid branch to take,
    matching the Day 1 diagrams where every call eventually lands in some
    named flow rather than a dead end."""
    lowered = customer_text.lower()

    appointment_intent = appt.detect_appointment_intent(customer_text)
    if appointment_intent == "cancel":
        return "appointment_cancellation"
    if appointment_intent == "reschedule":
        return "appointment_rescheduling"

    if any(kw in lowered for kw in _RETURNING_KEYWORDS):
        return "returning_customer"

    if any(kw in lowered for kw in _INVESTMENT_KEYWORDS):
        return "investment_inquiry"
    if any(kw in lowered for kw in _COMMERCIAL_KEYWORDS):
        return "commercial_inquiry"
    if any(kw in lowered for kw in _RENTAL_KEYWORDS):
        return "rental_inquiry"

    return "buyer_inquiry"


if __name__ == "__main__":
    samples = [
        "Mujhe DHA mein ghar rent par chahiye.",
        "Commercial shop dekhni hai Gulberg mein.",
        "Investment ke liye achi property batayein, return kaisa hoga?",
        "Maine pehle bhi call kiya tha aap se.",
        "Mera appointment cancel kar dein please.",
        "Waqt change karna hai, kisi aur din milte hain.",
        "3 crore budget hai, DHA mein ghar dekhna hai.",
    ]
    for s in samples:
        print(f"{s!r} -> {classify_call_intent(s)}")
