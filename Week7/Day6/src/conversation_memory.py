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

# Email addresses: capture standard user@domain.ext from speech
# Customers often say or spell out email addresses including 'at' / '@' / 'gmail'
# so we also handle the common spoken form "username at gmail dot com"
_EMAIL_LITERAL_PATTERN = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"
)
_EMAIL_SPOKEN_PATTERN = re.compile(
    r"([a-zA-Z0-9_.+-]+)\s+(?:at|@|ایٹ)\s+([a-zA-Z0-9.-]+)\s+"
    r"(?:dot|\.)\s+(com|net|org|pk|io|co)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NameParseResult:
    """One contextual client-name extraction result.

    confidence is deliberately coarse rather than pretending we have an ASR
    probability for the name itself:
      >= 0.85  safe to persist in the current conversational context
      0.55-0.84 plausible, but ask the caller to confirm once
      < 0.55    ignore and keep asking for the name
    """
    name: Optional[str]
    confidence: float = 0.0
    source: str = "none"


# Strong self-introduction patterns. These are high-confidence because the
# caller explicitly anchors the following words as their own name.
_NAME_PATTERNS = [
    re.compile(
        r"\bmera\s+naam\s+"
        r"([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,3}?)"
        r"(?=\s+(?:hai|hain|hoon)\b|[.!?،۔]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,3})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmain\s+([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,3})\s+bol\s+(?:raha|rahi)\s+hoon\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthis\s+is\s+([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,3})\s+speaking\b",
        re.IGNORECASE,
    ),
]

# Native Urdu equivalents. The broad "نام X ہے" pattern intentionally
# handles imperfect STT such as "میں ذرا نام علی ہے" seen in live tests.
_NAME_PATTERNS_URDU_SCRIPT = [
    re.compile(r"میرا\s+نام\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,3}?)(?=\s+(?:ہے|ہوں|ہیں)|$)"),
    re.compile(r"نام\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,3}?)(?=\s+(?:ہے|ہوں|ہیں)|$)"),
    re.compile(r"میں\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,3}?)\s+بول\s+(?:رہا|رہی)\s+ہوں"),
]

# Words that are common one-turn replies but are obviously not a person's
# name. This keeps context-mode capture from turning "ji", "hello", or
# "apartment" into CRM client_name values.
_NAME_RESPONSE_STOPWORDS = {
    "ji", "jee", "haan", "han", "yes", "no", "nahi", "nahin", "hello", "helo",
    "sir", "madam", "okay", "ok", "thanks", "thank", "shukriya",
    "apartment", "house", "plot", "shop", "office", "property", "booking",
    "appointment", "reschedule", "cancel", "dha", "phase", "bahria", "gulberg",
    "جی", "ہاں", "نہیں", "ہیلو", "سر", "میڈم", "شکریہ", "اپارٹمنٹ", "گھر",
    "پلاٹ", "دکان", "دفتر", "پراپرٹی", "اپوائنٹمنٹ", "ڈی", "ایچ", "اے",
}

_NAME_TRAILING_FILLERS_LATIN = {
    "hai", "hain", "hoon", "hun", "ji", "jee", "sir", "madam", "hello", "helo",
}
_NAME_TRAILING_FILLERS_URDU = {"ہے", "ہیں", "ہوں", "جی", "سر", "میڈم", "ہیلو"}


def _clean_name_candidate(candidate: str) -> Optional[str]:
    value = re.sub(r"[,:;!?]+", " ", candidate or "")
    value = " ".join(value.split()).strip(" .'-")
    if not value:
        return None

    words = value.split()
    while words and words[-1].lower() in _NAME_TRAILING_FILLERS_LATIN:
        words.pop()
    while words and words[-1] in _NAME_TRAILING_FILLERS_URDU:
        words.pop()

    if not words or len(words) > 4:
        return None

    # A candidate consisting entirely of common conversational/domain words
    # is not a name. Mixed candidates are allowed because real names can
    # contain short particles such as "Ali Raza".
    if all(word.lower() in _NAME_RESPONSE_STOPWORDS for word in words):
        return None

    # Reject candidates containing digits or real-estate/date-time tokens.
    if any(any(ch.isdigit() for ch in word) for word in words):
        return None

    lowered = {word.lower() for word in words}

    # If name capture crossed into the next property sentence (e.g.
    # "Mera naam Zain hai. DHA Phase 6..."), reject the contaminated candidate
    # rather than storing "Zain Hai Dha Phase" as a CRM name.
    hard_domain_words = {
        "dha", "phase", "property", "apartment", "house", "plot", "shop",
        "office", "warehouse", "booking", "appointment", "budget", "crore",
        "lakh", "marla", "kanal",
    }
    if lowered & hard_domain_words:
        return None

    if lowered & {"august", "september", "october", "november", "december", "baje", "bajy"}:
        return None

    cleaned = " ".join(words)
    # Preserve native Urdu exactly as STT returned it; title-casing only
    # makes sense for Latin script.
    if re.search(r"[A-Za-z]", cleaned) and not re.search(r"[\u0600-\u06FF]", cleaned):
        cleaned = cleaned.title()
    return cleaned


def extract_client_name(text: str, expect_name: bool = False) -> NameParseResult:
    """Extract a client name with conversational context.

    When ``expect_name`` is True, the previous agent turn explicitly asked
    for the caller's name. In that state a short answer such as just "Ali"
    is valid and should be captured; outside that state, bare words are never
    guessed to be names.
    """
    raw = " ".join((text or "").strip().split())
    if not raw:
        return NameParseResult(None)

    for pattern in _NAME_PATTERNS:
        match = pattern.search(raw)
        if match:
            name = _clean_name_candidate(match.group(1))
            if name:
                return NameParseResult(name, 0.99, "explicit_latin")

    for pattern in _NAME_PATTERNS_URDU_SCRIPT:
        match = pattern.search(raw)
        if match:
            name = _clean_name_candidate(match.group(1))
            if name:
                # The broader native-script STT form is slightly less
                # certain than an exact "mera naam" phrase.
                confidence = 0.96 if raw.startswith("میرا نام") else 0.78
                return NameParseResult(name, confidence, "explicit_urdu")

    # Loose Roman Urdu STT variants such as "naam Ali hai" or
    # "main zara naam Ali hai". We keep these below the auto-save threshold
    # so the booking node confirms once rather than silently storing a bad
    # ASR guess.
    loose = re.search(
        r"(?:^|\s)(?:mera\s+)?(?:naam|name)\s+(?:is\s+)?"
        r"([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,3}?)"
        r"(?=\s+(?:hai|hain|hoon|ji|sir|hello)\b|$)",
        raw,
        flags=re.IGNORECASE,
    )
    if loose:
        name = _clean_name_candidate(loose.group(1))
        if name:
            return NameParseResult(name, 0.78, "loose_latin")

    if expect_name:
        # Remove predictable conversational wrapping when the system has just
        # asked "aap ka naam?". This makes "Ali", "Ali ji", and
        # "mera naam Ali" valid without weakening global extraction.
        candidate = raw
        candidate = re.sub(
            r"^(?:ji|jee|haan|han|yes|hello|helo|sir)[,\s]+",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r"^(?:mera\s+naam(?:\s+is)?|my\s+name(?:\s+is)?|naam)\s+",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(r"^(?:جی|ہاں|ہیلو|سر)[،,\s]+", "", candidate)
        candidate = re.sub(r"^(?:میرا\s+نام|نام)\s+", "", candidate)

        name = _clean_name_candidate(candidate)
        if name:
            # Context is strong: the previous turn asked for a name. Save a
            # short, clean response directly. Longer/noisier answers are
            # treated as plausible and confirmed once.
            words = name.split()
            confidence = 0.94 if len(words) <= 3 else 0.72
            return NameParseResult(name, confidence, "expected_name_reply")

    return NameParseResult(None)


def parse_phone_number(text: str) -> Optional[str]:
    m = _PHONE_PATTERN.search(text)
    return m.group(0) if m else None


def parse_email_address(text: str) -> Optional[str]:
    """Extract a customer email address from text.
    Handles both literal form (user@gmail.com) and spoken form
    ("user at gmail dot com")."""
    raw = (text or "").strip()
    # Try literal email first (highest confidence)
    m = _EMAIL_LITERAL_PATTERN.search(raw)
    if m:
        return m.group(0).lower()
    # Try spoken form: "imamazubair at gmail dot com"
    m = _EMAIL_SPOKEN_PATTERN.search(raw)
    if m:
        return f"{m.group(1)}@{m.group(2)}.{m.group(3)}".lower()
    return None


def parse_client_name(
    text: str,
    expect_name: bool = False,
    min_confidence: float = 0.85,
) -> Optional[str]:
    result = extract_client_name(text, expect_name=expect_name)
    if result.name and result.confidence >= min_confidence:
        return result.name
    return None


@dataclass
class ConversationSlots:
    """Everything the agent currently 'knows' about this caller's intent."""
    client_name: Optional[str] = None      # Day 4: needed for calendar events
    client_phone: Optional[str] = None     # Day 4: needed for calendar events
    client_email: Optional[str] = None     # Optional: send confirmation email to customer too
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

    def update_from_customer_text(self, text: str, expect_name: bool = False):
        name = parse_client_name(text, expect_name=expect_name)
        if name:
            self.slots.client_name = name

        phone = parse_phone_number(text)
        if phone:
            self.slots.client_phone = phone

        email = parse_email_address(text)
        if email:
            self.slots.client_email = email
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
            # --- DHA phases (all numeric and ordinal variants Vapi STT produces) ---
            "dha phase 6": "DHA Phase 6", "dha phase six": "DHA Phase 6",
            "dha phase 2": "DHA Phase 2", "dha phase two": "DHA Phase 2",
            "dha phase 8": "DHA Phase 8", "dha phase eight": "DHA Phase 8",
            "dha phase ath": "DHA Phase 8", "dha phase aath": "DHA Phase 8",
            "dha phase 5": "DHA Phase 6",  # Phase 5 not in DB, fallback to 6
            "dha phase five": "DHA Phase 6",
            "dha phase 1": "DHA Phase 2",  # Phase 1 not in DB, fallback to 2
            "dha phase one": "DHA Phase 2",
            "dha": "DHA Phase 6",  # bare DHA defaults to phase 6
            # --- Bahria Town — every phonetic spelling Vapi/Deepgram produces ---
            "bahria town": "Bahria Town",
            "bahriya town": "Bahria Town",
            "behriya town": "Bahria Town",
            "bahria": "Bahria Town",
            "bahriya": "Bahria Town",
            "baharia town": "Bahria Town",
            "baharia": "Bahria Town",
            # --- Other areas ---
            "gulberg": "Gulberg",
            "gulshan-e-iqbal": "Gulshan-e-Iqbal",
            "gulshan iqbal": "Gulshan-e-Iqbal",
            "gulshan": "Gulshan-e-Iqbal",
            "johar town": "Johar Town",
            "johar": "Johar Town",
            "wapda town": "Wapda Town",
            "wapda": "Wapda Town",
            "blue area": "Blue Area",
            "g-11": "G-11", "g 11": "G-11",
            "f-10": "F-10", "f 10": "F-10",
            "f-11": "F-11", "f 11": "F-11",
            "pechs": "PECHS",
            "clifton": "Clifton",
            "bahadurabad": "Bahadurabad",
            "bahadarabad": "Bahadurabad",
            # --- Native Urdu script variants ---
            "ڈی ایچ اے فیز 6": "DHA Phase 6",
            "ڈی ایچ اے فیز 2": "DHA Phase 2",
            "ڈی ایچ اے فیز 8": "DHA Phase 8",
            "ڈی ایچ اے فیز سیکس": "DHA Phase 6",
            "ڈی ایچ اے فیز چھ": "DHA Phase 6",
            "ڈی ایچ اے فیز آٹھ": "DHA Phase 8",
            "ڈی ایچ اے فیز اٹھ": "DHA Phase 8",
            "ڈی ایچ اے فیز پانچ": "DHA Phase 6",  # Phase 5 not in DB
            "ڈی ایچ اے": "DHA Phase 6",
            "بحریہ ٹاؤن": "Bahria Town",
            "بحریہ": "Bahria Town",
            "بہریہ ٹاؤن": "Bahria Town",
            "بہریہ": "Bahria Town",
            "گلبرگ": "Gulberg",
            "گلشن اقبال": "Gulshan-e-Iqbal",
            "گلشن": "Gulshan-e-Iqbal",
            "جوہر ٹاؤن": "Johar Town",
            "جوہر": "Johar Town",
            "واپڈا ٹاؤن": "Wapda Town",
            "ایف 10": "F-10",
            "بہادر آباد": "Bahadurabad",
            "بہادرآباد": "Bahadurabad",
            "کلفٹن": "Clifton",
            "پیکس": "PECHS",
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