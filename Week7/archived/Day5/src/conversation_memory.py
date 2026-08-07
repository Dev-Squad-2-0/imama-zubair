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


def parse_pkr_amount(text: str) -> Optional[int]:
    text = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*crore", text)
    if m:
        return int(float(m.group(1)) * _CRORE)
    m = re.search(r"(\d+(?:\.\d+)?)\s*lakh", text)
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
_NAME_PATTERNS = [
    re.compile(r"mera naam ([A-Za-z]+(?:\s[A-Za-z]+)?)\s+(?:hai|hain)\b", re.IGNORECASE),
    re.compile(r"main ([A-Za-z]+(?:\s[A-Za-z]+)?)\s+bol (?:raha|rahi) hoon", re.IGNORECASE),
    re.compile(r"my name is ([A-Za-z]+(?:\s[A-Za-z]+)?)", re.IGNORECASE),
    re.compile(r"this is ([A-Za-z]+(?:\s[A-Za-z]+)?) speaking", re.IGNORECASE),
]


def parse_phone_number(text: str) -> Optional[str]:
    """Matches an already-well-formed phone number written/transcribed as a
    contiguous or lightly-hyphenated digit string. Doesn't understand a
    number dictated digit-by-digit ("zero three double zero...") - see
    extract_phone_digit_candidate() for that."""
    m = _PHONE_PATTERN.search(text)
    return m.group(0) if m else None


# ---- spoken digit-by-digit dictation ("zero three double zero double three
# double eight one two three four five") - live STT very plausibly renders a
# slowly-dictated phone number as digit words rather than numerals, which
# _PHONE_PATTERN can't match at all. ----

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "naught": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # Urdu digit words (Roman transliteration), same UrduLish spirit as the
    # rest of this module's phrasing
    "sifar": "0", "aik": "1", "ek": "1", "do": "2", "teen": "3",
    "char": "4", "chaar": "4", "panch": "5", "paanch": "5",
    "chhay": "6", "chhe": "6", "saat": "7", "aath": "8", "aat": "8", "nau": "9",
}
_MULTIPLIER_WORDS = {"double": 2, "triple": 3}

_PK_MOBILE_SHAPE = re.compile(r"^03\d{9}$")


def _spoken_digit_runs(text: str) -> List[str]:
    """Finds maximal runs of consecutive spoken/typed digits in text (e.g.
    "zero three double zero double three double eight one two three four
    five" -> a single 15-char digit run), handling bare digit words, typed
    numerals, and "double X"/"triple X" repeaters. Only runs of 6+ digits
    are returned - long enough to plausibly be (part of) a phone number, so
    a lone "do bedroom" or "teen crore" nearby doesn't get swept in."""
    tokens = re.findall(r"[a-zA-Z]+|\d+", text.lower())
    runs: List[str] = []
    current = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _MULTIPLIER_WORDS and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            digit = _DIGIT_WORDS.get(nxt) or (nxt if nxt.isdigit() and len(nxt) == 1 else None)
            if digit:
                current += digit * _MULTIPLIER_WORDS[tok]
                i += 2
                continue
        digit = _DIGIT_WORDS.get(tok)
        if digit is None and tok.isdigit():
            digit = tok
        if digit:
            current += digit
            i += 1
            continue
        if current:
            if len(current) >= 6:
                runs.append(current)
            current = ""
        i += 1
    if current and len(current) >= 6:
        runs.append(current)
    return runs


def _normalize_pk_mobile_digits(digits: str) -> str:
    """Strips a leading country-code prefix (+92/92/092) down to the local
    '0' so "923001234567" and "03001234567" normalize to the same shape.
    Returns the digits unchanged if no such prefix is present - validity
    (11 digits, starts with 03) is checked separately by callers via
    _PK_MOBILE_SHAPE, since an invalid-shaped candidate still needs to be
    surfaced (as "heard something, please repeat"), not silently dropped."""
    d = digits
    if d.startswith("0092"):
        return "0" + d[4:]
    if d.startswith("092"):
        return "0" + d[3:]
    if d.startswith("92") and len(d) >= 12:
        return "0" + d[2:]
    return d


def extract_phone_digit_candidate(text: str) -> Optional[str]:
    """Best-effort phone-number candidate from raw customer text: prefers
    an already-well-formed match (parse_phone_number), falls back to the
    longest spoken-digit run (_spoken_digit_runs) if there is no
    well-formed match. Returns a normalized digit string that may or may
    not actually be a valid 11-digit Pakistani mobile number - check with
    _PK_MOBILE_SHAPE.match() to tell "confidently heard, ready to confirm"
    from "heard something phone-number-shaped, but not 11 digits - ask
    again" (see ConversationMemory._update_phone below, which is the only
    caller that needs to make that distinction)."""
    direct = parse_phone_number(text)
    if direct:
        digits = re.sub(r"\D", "", direct)
        return _normalize_pk_mobile_digits(digits)

    runs = _spoken_digit_runs(text)
    if not runs:
        return None
    longest = max(runs, key=len)
    return _normalize_pk_mobile_digits(longest)


_AFFIRMATIVE_WORDS = ["haan ji", "ji haan", "haan", "yes", "sahi hai", "sahi", "correct", "bilkul theek", "ji bilkul"]
_NEGATIVE_WORDS = ["nahi", "ghalat", "no", "wrong", "galat"]


def _is_affirmative(lowered: str) -> bool:
    return any(w in lowered for w in _AFFIRMATIVE_WORDS)


def _is_negative(lowered: str) -> bool:
    return any(w in lowered for w in _NEGATIVE_WORDS)


def parse_client_name(text: str) -> Optional[str]:
    for pattern in _NAME_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip().title()
    return None


@dataclass
class ConversationSlots:
    """Everything the agent currently 'knows' about this caller's intent."""
    client_name: Optional[str] = None      # Day 4: needed for calendar events
    client_phone: Optional[str] = None     # Day 4: needed for calendar events
    client_phone_pending: Optional[str] = None    # heard, not yet confirmed by the customer
    client_phone_confirmed: bool = False          # True once the customer says the read-back is correct
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

    def _update_phone(self, text: str) -> str:
        """Phone-capture/confirmation state machine for one customer turn.
        Returns text with any directly-matched numeral phone number
        stripped out (so parse_pkr_amount()'s raw-number fallback can't
        misread it as a budget figure) - unchanged otherwise.

        A captured number never becomes client_phone directly - it always
        lands in client_phone_pending first and needs a customer "yes" to
        a read-back before nodes.py's booking gate will treat it as known.
        This catches both failure modes a plain always-well-formed regex
        match had zero handling for: a number dictated digit-by-digit
        ("zero three double zero...", via extract_phone_digit_candidate)
        that the old regex couldn't match at all, and a confidently-parsed
        but simply wrong number (STT mishears a digit) that used to get
        used for booking/CRM with no chance to catch the mistake."""
        lowered = text.lower()
        direct_match = parse_phone_number(text)

        if self.slots.client_phone_pending and not self.slots.client_phone_confirmed:
            pending_is_valid_shape = bool(_PK_MOBILE_SHAPE.match(self.slots.client_phone_pending))
            # only a valid-shaped (11-digit, 03...) pending candidate is
            # ever actually asked "sahi hai?" (see nodes.py's
            # _phone_clarification_reply) - an affirmative-sounding reply
            # to an invalid-shaped one isn't a real confirmation of
            # anything, since that question was never asked
            if pending_is_valid_shape and direct_match is None and _is_affirmative(lowered):
                self.slots.client_phone = self.slots.client_phone_pending
                self.slots.client_phone_confirmed = True
                self.slots.client_phone_pending = None
                return text
            if direct_match is None and _is_negative(lowered):
                self.slots.client_phone_pending = None
                return text
            # neither yes nor no - the customer may have just restated the
            # number, fall through and treat this turn as a fresh candidate

        candidate = extract_phone_digit_candidate(text)
        if candidate:
            self.slots.client_phone_pending = candidate
            self.slots.client_phone_confirmed = False
            self.slots.client_phone = None
            if direct_match:
                text = _PHONE_PATTERN.sub("", text)

        return text

    def update_from_customer_text(self, text: str):
        name = parse_client_name(text)
        if name:
            self.slots.client_name = name

        text = self._update_phone(text)

        lowered = text.lower()

        amount = parse_pkr_amount(text)
        if amount:
            self.slots.budget = amount

        # maps loose customer phrasing to the canonical area name stored in the DB
        area_aliases = {
            "dha phase 6": "DHA Phase 6",
            "dha": "DHA Phase 6",   # only DHA phase in this demo dataset
            "bahria town": "Bahria Town",
            "gulberg": "Gulberg",
            "gulshan-e-iqbal": "Gulshan-e-Iqbal",
            "f-10": "F-10", "f-11": "F-11", "e-11": "E-11",
        }
        for alias in sorted(area_aliases, key=len, reverse=True):
            if alias in lowered:
                self.slots.area = area_aliases[alias]
                break

        for city in ["lahore", "karachi", "islamabad"]:
            if city in lowered:
                self.slots.city = city.title()
                break

        for purpose_kw, purpose_val in [("rent", "rent"), ("kiraya", "rent"),
                                          ("invest", "investment"), ("buy", "buy"),
                                          ("khareed", "buy"), ("commercial", "commercial")]:
            if purpose_kw in lowered:
                self.slots.purpose = purpose_val
                break

        m = re.search(r"(\d+)\s*(?:bed|bedroom|kamre)", lowered)
        if m:
            self.slots.bedrooms = int(m.group(1))

        if any(p in lowered for p in ["sasti", "kam budget", "cheaper", "affordable"]):
            # "us se sasti koi option" -> lower the ceiling below the last shown price
            if self.slots.last_shown_min_price:
                self.slots.budget = self.slots.last_shown_min_price - 1

        if any(p in lowered for p in ["nahi chahiye", "nahi", "not interested", "no thanks"]):
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
