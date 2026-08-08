"""
Day 3 - Task 3: Context Memory

Keeps a running "slot" state per call so the agent understands references
like "us se sasti koi option?" (cheaper than that one) without the customer
repeating themselves. This is deliberately simple: a slot dictionary plus a
short turn history, not a separate vector memory store. For a single phone
call (a few minutes), that's all that's needed, and it's easy for an intern
to explain in a review.

Example flow this supports:
    Turn 1  "Budget 3 crore hai"              -> slots.budget = 30,000,000
    Turn 2  "DHA mein kya options hain?"       -> slots.area = "DHA Phase 6"
                                                   (uses budget from turn 1)
    Turn 3  "Us se sasti koi option?"          -> reads slots.last_shown_price
                                                   and lowers the budget ceiling

client_name / client_phone (added for Day 4, Google Calendar needs both):
only fire on explicit self-introduction phrasing ("mera naam X hai", "my
name is X") or a Pakistani mobile number pattern, not on any arbitrary text.
Appointment date/time slots don't exist yet, that parsing is separate Day 4 work.
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# crude PKR parser: "3 crore", "80 lakh", "3.5 crore", "15000000"
_CRORE = 10_000_000
_LAKH = 100_000

# Eastern Arabic-Indic digits (۰-۹, used in Urdu script) -> ASCII digits.
# This is NOT transliteration of language/meaning - a digit is the same
# number regardless of which numeral system renders it, so normalizing
# ۳ -> 3 before regex parsing carries zero translation risk, unlike
# converting words. Deepgram can return either digit style depending on
# the transcript, and _CRORE/_LAKH-suffixed amounts need ASCII digits to
# match the existing \d+ patterns below.
_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _normalize_digits(text: str) -> str:
    return text.translate(_URDU_DIGITS)


def parse_pkr_amount(text: str) -> Optional[int]:
    text = _normalize_digits(text).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:crore|کروڑ)", text)
    if m:
        return int(float(m.group(1)) * _CRORE)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|لاکھ)", text)
    if m:
        return int(float(m.group(1)) * _LAKH)
    m = re.search(r"\b(\d{6,})\b", text)  # raw number like 15000000
    if m:
        return int(m.group(1))
    return None


# Pakistani mobile numbers: 03XX-XXXXXXX, 03XXXXXXXXX, or +92 3XX XXXXXXX
_PHONE_PATTERN = re.compile(r"(?:\+92[\s-]?|0)3\d{2}[\s-]?\d{7}\b")

# Only fires on explicit self-introduction phrasing, not on any arbitrary
# name-shaped text, since guessing a name from loose text is unreliable.
#
# Two script families, not a transliteration layer: STT (Deepgram,
# language=ur) can return either Roman "UrduLish" text or native Urdu
# script depending on how the customer actually speaks, and there is no
# reliable way to predict which one shows up on a given call. Rather than
# converting everything through a transliteration step (extra latency, a
# new failure mode, and would still need to guess the "correct" spelling of
# a name either way), the same structural phrase patterns are just written
# twice: once matching Roman letters, once matching the Arabic/Urdu
# Unicode block (U+0600-U+06FF). Both are equally "the real detector", not
# a fallback for each other.
_NAME_PATTERNS = [
    re.compile(r"mera naam ([A-Za-z]+(?:\s[A-Za-z]+)?)\s+(?:hai|hain)\b", re.IGNORECASE),
    re.compile(r"main ([A-Za-z]+(?:\s[A-Za-z]+)?)\s+bol (?:raha|rahi) hoon", re.IGNORECASE),
    re.compile(r"my name is ([A-Za-z]+(?:\s[A-Za-z]+)?)", re.IGNORECASE),
    re.compile(r"this is ([A-Za-z]+(?:\s[A-Za-z]+)?) speaking", re.IGNORECASE),
]

# Native-script equivalent of "mera naam X hai" / "main X bol raha/rahi hoon".
# Captured as the raw Unicode span (no .title()-casing, that's a Latin-script
# concept) - non-greedy up to the "ہے"/"ہوں" that closes the phrase.
_NAME_PATTERNS_URDU_SCRIPT = [
    re.compile(r"میرا نام\s+([\u0600-\u06FF]+(?:\s[\u0600-\u06FF]+)?)\s+ہے"),
    re.compile(r"میں\s+([\u0600-\u06FF]+(?:\s[\u0600-\u06FF]+)?)\s+بول (?:رہا|رہی) ہوں"),
]


def parse_phone_number(text: str) -> Optional[str]:
    m = _PHONE_PATTERN.search(text)
    return m.group(0) if m else None


def parse_client_name(text: str) -> Optional[str]:
    for pattern in _NAME_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip().title()
    for pattern in _NAME_PATTERNS_URDU_SCRIPT:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()  # no .title() - not a Latin-script concept
    return None


@dataclass
class ConversationSlots:
    """Everything the agent currently 'knows' about this caller's intent."""
    client_name: Optional[str] = None      # Day 4: needed for calendar events
    client_phone: Optional[str] = None     # Day 4: needed for calendar events
    budget: Optional[int] = None
    city: Optional[str] = None
    area: Optional[str] = None
    purpose: Optional[str] = None          # buy, rent, commercial, investment
    bedrooms: Optional[int] = None
    property_type: Optional[str] = None
    last_shown_property_ids: List[int] = field(default_factory=list)
    last_shown_min_price: Optional[int] = None
    last_shown_max_price: Optional[int] = None
    pending_appointment: Optional[Dict[str, Any]] = None
    decline_count: int = 0                 # tracks "no thanks" for the no-pushing-past-2x rule
    # No appointment date/time slots yet - parsing "kal 5 baje" style Urdu
    # date/time expressions is separate work, left for Day 4.


@dataclass
class ConversationMemory:
    """Full memory for one call: slots + turn history.

    session_id: stable identifier for this call, auto-generated so every
    ConversationMemory (the mic-loop/voice_pipeline.py path included, not
    just api.py's n8n-driven sessions) has one to log CRM events under -
    without it, appointment_management.py has no key to write CRM rows
    against for calls that don't go through api.py's HTTP layer."""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    slots: ConversationSlots = field(default_factory=ConversationSlots)
    history: List[Dict[str, str]] = field(default_factory=list)

    def add_turn(self, speaker: str, text: str):
        self.history.append({"speaker": speaker, "text": text})

    def recent_context(self, n=6) -> str:
        """Last n turns as plain text, used as LLM context alongside slots."""
        return "\n".join(f"{t['speaker']}: {t['text']}" for t in self.history[-n:])

    # ---- slot updates, called by conversation_agent.py after each customer turn ----

    def update_from_customer_text(self, text: str):
        name = parse_client_name(text)
        if name:
            self.slots.client_name = name

        phone = parse_phone_number(text)
        if phone:
            self.slots.client_phone = phone
            # strip the phone digits so parse_pkr_amount()'s raw-number
            # fallback (\d{6,}) can't misread them as a budget figure
            text = _PHONE_PATTERN.sub("", text)

        text = _normalize_digits(text)
        lowered = text.lower()

        amount = parse_pkr_amount(text)
        if amount:
            self.slots.budget = amount

        # Maps loose customer phrasing to the canonical area name stored in
        # the DB. IMPORTANT - this list is manually maintained and can drift
        # out of sync with the actual properties table (e.g. "Johar Town"
        # and "DHA Phase 2" showed up in real live-pipeline data but weren't
        # in this dict at all, in EITHER script, until this fix - a stale
        # entry here doesn't error, it just silently returns unfiltered
        # results, which is much harder to notice). Worth checking this
        # against `SELECT DISTINCT area FROM properties` periodically, or
        # better, sourcing it dynamically from structured_retrieval.py
        # instead of hardcoding it here at all.
        area_aliases = {
            "dha phase 6": "DHA Phase 6", "dha phase 2": "DHA Phase 2",
            "dha": "DHA Phase 6",  # ambiguous bare "DHA" defaults to phase 6
            "bahria town": "Bahria Town",
            "gulberg": "Gulberg",
            "gulshan-e-iqbal": "Gulshan-e-Iqbal",
            "johar town": "Johar Town",
            "f-10": "F-10", "f-11": "F-11", "e-11": "E-11",
            # native Urdu script - same canonical values, not a fallback list
            "ڈی ایچ اے فیز 6": "DHA Phase 6", "ڈی ایچ اے فیز 2": "DHA Phase 2",
            "ڈی ایچ اے": "DHA Phase 6",
            "بحریہ ٹاؤن": "Bahria Town",
            "گلبرگ": "Gulberg",
            "گلشن اقبال": "Gulshan-e-Iqbal",
            "جوہر ٹاؤن": "Johar Town",
            "ایف 10": "F-10",
        }
        for alias in sorted(area_aliases, key=len, reverse=True):
            if alias in lowered:
                self.slots.area = area_aliases[alias]
                break

        _CITY_ALIASES = {
            "lahore": "Lahore", "karachi": "Karachi", "islamabad": "Islamabad",
            "لاہور": "Lahore", "کراچی": "Karachi", "اسلام آباد": "Islamabad",
        }
        for city_kw in sorted(_CITY_ALIASES, key=len, reverse=True):
            if city_kw in lowered:
                self.slots.city = _CITY_ALIASES[city_kw]
                break

        for purpose_kw, purpose_val in [
            ("rent", "rent"), ("kiraya", "rent"), ("invest", "investment"),
            ("buy", "buy"), ("khareed", "buy"), ("commercial", "commercial"),
            ("کرایہ", "rent"), ("سرمایہ کاری", "investment"), ("انویسٹمنٹ", "investment"),
            ("خریدنا", "buy"), ("خریدیں", "buy"), ("کمرشل", "commercial"),
        ]:
            if purpose_kw in lowered:
                self.slots.purpose = purpose_val
                break

        m = re.search(r"(\d+)\s*(?:bed|bedroom|kamre|کمرے|بیڈ روم|بیڈروم)", lowered)
        if m:
            self.slots.bedrooms = int(m.group(1))

        if any(p in lowered for p in ["sasti", "kam budget", "cheaper", "affordable",
                                        "سستی", "کم بجٹ", "سستا"]):
            # "us se sasti koi option" -> lower the ceiling below the last shown price
            if self.slots.last_shown_min_price:
                self.slots.budget = self.slots.last_shown_min_price - 1

        # .lower() is a no-op on Arabic-script text (no case there), so one
        # substring check covers both script families once both keyword
        # sets are in the same list - no separate branch needed.
        _DECLINE_PHRASES = [
            "nahi chahiye", "not interested", "no thanks",
            # native Urdu script - see _NAME_PATTERNS_URDU_SCRIPT's comment
            # above for why this is a second real pattern set, not a
            # transliteration step
            "نہیں چاہیے", "دلچسپی نہیں", "شکریہ نہیں",
        ]
        # Bare "no"/"نہیں" with nothing else - confirmed live: "گودام نہیں"
        # (not a warehouse), embedded in a longer property-preference
        # sentence, matched a bare "نہیں" substring check and incorrectly
        # registered as the customer declining the whole conversation,
        # when they were actually just excluding one property TYPE. A
        # short, standalone "نہیں"/"nahi" (like the customer just saying
        # "نہیں" alone in response to a suggestion) is a real, high-
        # confidence decline signal; the same word buried in a longer,
        # information-rich sentence usually isn't - it's negating one
        # specific word nearby, not the whole exchange. Word-count cutoff
        # is a blunt instrument but a safe one: false negatives here just
        # mean a real short decline phrase should be added to the list
        # above instead, not that this heuristic needs to get cleverer.
        _BARE_NO_WORDS = ["nahi", "نہیں"]
        is_bare_no = len(text.split()) <= 4 and any(
            w == lowered.strip() or lowered.strip().startswith(w + " ") or lowered.strip().endswith(" " + w)
            for w in _BARE_NO_WORDS
        )
        if any(p in lowered for p in _DECLINE_PHRASES) or is_bare_no:
            self.slots.decline_count += 1

    def record_shown_properties(self, properties: List[Dict[str, Any]]):
        self.slots.last_shown_property_ids = [p["id"] for p in properties]
        if properties:
            prices = [p["price_pkr"] for p in properties]
            self.slots.last_shown_min_price = min(prices)
            self.slots.last_shown_max_price = max(prices)

    def as_recommendation_kwargs(self) -> Dict[str, Any]:
        """Slots translated straight into recommendation_engine.recommend_properties()
        kwargs, so conversation_agent.py doesn't have to re-map fields."""
        return {
            "budget": self.slots.budget,
            "city": self.slots.city,
            "area": self.slots.area,
            "bedrooms": self.slots.bedrooms,
            "purpose": self.slots.purpose,
        }


if __name__ == "__main__":
    mem = ConversationMemory()

    mem.add_turn("customer", "Mera naam Ahmed hai, mera number 0300-1234567 hai.")
    mem.update_from_customer_text("Mera naam Ahmed hai, mera number 0300-1234567 hai.")
    print("After intro turn slots:", mem.slots)

    mem.add_turn("customer", "Budget 3 crore hai.")
    mem.update_from_customer_text("Budget 3 crore hai.")
    print("After turn 1 slots:", mem.slots)

    mem.add_turn("customer", "DHA mein kya options hain?")
    mem.update_from_customer_text("DHA mein kya options hain?")
    print("After turn 2 slots:", mem.slots)

    # simulate the agent having shown properties priced 3.2cr-5.5cr from DHA
    mem.record_shown_properties([
        {"id": 101, "price_pkr": 32_000_000},
        {"id": 105, "price_pkr": 55_000_000},
    ])

    mem.add_turn("customer", "Us se sasti koi option?")
    mem.update_from_customer_text("Us se sasti koi option?")
    print("After turn 3 slots:", mem.slots)
    print("\nRecommendation kwargs derived from memory:", mem.as_recommendation_kwargs())