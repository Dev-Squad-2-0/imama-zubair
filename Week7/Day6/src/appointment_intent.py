"""
Day 4 - appointment intent detection + date/time parsing.

"""

import re
from datetime import datetime, timedelta
from typing import Optional


# ---------- Intent detection ----------

# Each list also carries native Urdu-script keywords, not a transliteration
# of the Roman ones - same reasoning as conversation_memory.py's name/decline
# patterns: STT can hand back either script depending on how the customer
# speaks, and English loanwords ("book", "appointment", "cancel",
# "reschedule") commonly get rendered phonetically IN Urdu script by Deepgram
# ("بک" for "book", "اپوائنٹمنٹ" for "appointment") rather than transliterated
# to Roman letters - a plain Roman "book kar" pattern can never match that.
_CANCEL_KEYWORDS = [
    "cancel kar", "cancel ker", "appointment cancel", "visit cancel",
    "cancel karna", "cancel krna", "nahi aana ab", "appointment khatam",
    "کینسل کر", "اپوائنٹمنٹ کینسل", "وزٹ کینسل", "اب نہیں آنا", "اپوائنٹمنٹ ختم",
]
_RESCHEDULE_KEYWORDS = [
    "reschedule", "re schedule", "reshedule", "reschedul",
    "time change", "waqt tabdeel", "aage kar do", "date change",
    "time badal", "waqt badal", "kisi aur din", "kisi aur waqt",
    "ری شیڈول", "ریشیڈول", "ری شیڈیول", "ریشیڈیول",
    "وقت تبدیل", "آگے کر دیں", "تاریخ تبدیل", "وقت بدل",
    "کسی اور دن", "کسی اور وقت",
]

# Deepgram often renders the English loanword "reschedule" phonetically in
# Urdu script instead of returning the literal English token. Real examples
# observed in the live pipeline include:
#   "ریس کیجول"
#   "ریز کے جل"
# These are semantically unambiguous in appointment context, so recognize
# their phonetic shape deterministically rather than making the caller repeat
# the command until STT happens to spell "reschedule" correctly.
_RESCHEDULE_PHONETIC_PATTERNS = [
    # Roman-English / common ASR misspellings.
    r"\b(?:re[\s-]?schedule|reschedule|reshedule|reschedul)\b",

    # Urdu-script versions close to "re-schedule".
    r"(?:ری\s*شیڈول|ریشیڈول|ری\s*شیڈیول|ریشیڈیول)",

    # Deepgram phonetic fragments:
    #   ریس کیجول  -> ریس + کی + جول
    #   ریز کے جل -> ریز + کے + جل
    # Also tolerates the same fragments with spaces collapsed.
    r"(?:ریس|ریز)\s*(?:کی|کے|ک)?\s*(?:جول|جل|جیول|کجول)",
]


def _looks_like_reschedule(customer_text: str) -> bool:
    lowered = (customer_text or "").lower().strip()

    if any(kw in lowered for kw in _RESCHEDULE_KEYWORDS):
        return True

    return any(
        re.search(pattern, lowered, flags=re.IGNORECASE)
        for pattern in _RESCHEDULE_PHONETIC_PATTERNS
    )
_APPOINTMENT_REFERENCE_KEYWORDS = [
    "appointment", "visit", "meeting",
    "اپوائنٹمنٹ", "وزٹ", "ملاقات",
]

_BOOK_KEYWORDS = [
    "book kar", "book ker", "booking", "booking kar", "booking ker",
    "booking karna", "appointment book", "visit book", "book karna",
    "schedule kar", "visit fix", "milna chahta", "milna chahti", "site visit",
    "appointment lena", "appointment chahiye",
    "بکنگ", "بوکنگ", "بکنگ کرنا", "بکنگ کر", "بوکنگ کرنا",
    "بک کر", "اپوائنٹمنٹ بک", "وزٹ بک", "بک کرنا", "شیڈول کر", "وزٹ فکس",
    "ملنا چاہتی", "ملنا چاہتا", "سائٹ وزٹ", "اپوائنٹمنٹ لینا", "اپوائنٹمنٹ چاہیے",
]

_BOOK_PHONETIC_PATTERNS = [
    r"(?:بکنگ|بوکنگ)\s*(?:کر|کرنا|کرو|کروانا|کروا|چاہتا|چاہتی)?",
    r"(?:بک|بکے|بکی|بوک)\s*(?:کر|کرنا|کرو|کروانا|کروا|کرانا)\b",
    r"\b(?:book|booking|buking|boking)\s*(?:kar|ker|kr|karna|kerna)?\b",
]


def _looks_like_book(customer_text: str) -> bool:
    lowered = (customer_text or "").lower().strip()
    if any(kw in lowered for kw in _BOOK_KEYWORDS):
        return True
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in _BOOK_PHONETIC_PATTERNS)


def resolve_stateful_appointment_intent(
    detected_intent: Optional[str],
    previous_intent: Optional[str],
    last_write_action: Optional[dict] = None,
) -> Optional[str]:
    """Keep the active appointment flow until THIS flow's write succeeds.

    A historical appointment restored from CRM must not terminate a newly
    started booking. Completion is based only on the current write action.
    """
    if detected_intent is not None:
        return detected_intent

    last_write = last_write_action or {}
    if previous_intent in {"book", "reschedule", "cancel"}:
        completed_this_flow = (
            last_write.get("kind") == previous_intent
            and last_write.get("success") is True
        )
        if not completed_this_flow:
            return previous_intent
    return None


def detect_appointment_intent(customer_text: str, has_existing_appointment: bool = False) -> Optional[str]:
    """Returns "cancel", "reschedule", "book", or None.

    Explicit keywords still win. When the graph already has a booked
    appointment, a caller can naturally say something like
    ``کیا اپوائنٹمنٹ پرسوں 12 بجے کر سکتے ہیں؟`` without literally saying
    "reschedule". In that context an appointment reference plus a real
    date/time is enough to mean reschedule; without existing appointment
    state the same sentence is *not* silently reinterpreted.
    """
    lowered = customer_text.lower()

    if any(kw in lowered for kw in _CANCEL_KEYWORDS):
        return "cancel"
    if _looks_like_reschedule(customer_text):
        return "reschedule"
    if _looks_like_book(customer_text):
        return "book"

    if (
        has_existing_appointment
        and any(kw in lowered for kw in _APPOINTMENT_REFERENCE_KEYWORDS)
        and parse_appointment_datetime(customer_text) is not None
    ):
        return "reschedule"

    return None


# ---------- Date/time parsing ----------

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    # native Urdu script - same reasoning as every other script gap fixed
    # this session: STT can hand back either script, and a Roman-only list
    # silently fails on perfectly ordinary native-script phrasing
    "پیر": 0, "منگل": 1, "بدھ": 2, "جمعرات": 3, "جمعہ": 4, "ہفتہ": 5, "اتوار": 6,
}

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
# sorted longest-first so "sept" is tried before "sep" matches as a prefix
_MONTH_NAMES_BY_LENGTH = sorted(_MONTHS, key=len, reverse=True)

_DEFAULT_HOUR_IF_NO_TIME_GIVEN = 12  # noon, used only when a day is parsed but no clock time at all

# Deepgram frequently returns spoken Urdu dates/times in native script, e.g.
# "آٹھ اگست کو چھ بجے" instead of "8 August 6 baje". The deterministic
# parser below originally understood Urdu relative-day words but not Urdu
# month names / number words, so perfectly valid booking details were lost.
_URDU_DATETIME_WORDS = {
    # months - native Urdu
    "جنوری": "january", "فروری": "february", "مارچ": "march",
    "اپریل": "april", "مئی": "may", "جون": "june", "جولائی": "july",
    # August has unusually noisy Urdu STT spellings. Keep the canonical
    # spelling plus variants observed in real Deepgram calls.
    "اگست": "august", "آگست": "august", "اگسٹ": "august",
    "آگسٹ": "august", "آگیسٹ": "august", "اگیسٹ": "august",
    "اوگس": "august", "اوگست": "august", "اوگرس": "august",
    "ستمبر": "september", "اکتوبر": "october",
    "نومبر": "november", "دسمبر": "december",

    # months - common Roman-Urdu / STT spellings
    "janwari": "january", "janvary": "january",
    "farwari": "february", "febuary": "february",
    "maarch": "march", "aprail": "april",
    "julai": "july", "july": "july",
    "agast": "august", "agust": "august",
    "sitambar": "september", "september": "september",
    "aktubar": "october", "octuber": "october",
    "navambar": "november", "novembar": "november",
    "disambar": "december", "decembar": "december",

    # Urdu number words (day-of-month + spoken clock hours)
    "ایک": "1", "دو": "2", "تین": "3", "چار": "4", "پانچ": "5",
    "چھ": "6", "سات": "7", "آٹھ": "8", "اٹھ": "8", "نو": "9",
    "دس": "10", "گیارہ": "11", "بارہ": "12", "تیرہ": "13",
    "چودہ": "14", "پندرہ": "15", "سولہ": "16", "سترہ": "17",
    "اٹھارہ": "18", "انیس": "19", "بیس": "20", "اکیس": "21",
    "بائیس": "22", "تئیس": "23", "چوبیس": "24", "پچیس": "25",
    "چھبیس": "26", "ستائیس": "27", "اٹھائیس": "28", "انتیس": "29",
    "تیس": "30", "اکتیس": "31",

    # Common Roman-Urdu number spellings returned by STT / typed by callers.
    "aik": "1", "ek": "1",
    "do": "2",
    "teen": "3", "tiin": "3",
    "chaar": "4", "char": "4",
    "paanch": "5", "panch": "5",
    "chay": "6", "chhe": "6", "che": "6", "chhai": "6",
    "saat": "7", "sat": "7",
    "aath": "8", "ath": "8",
    "nau": "9",
    "das": "10",
    "gyarah": "11", "giyara": "11", "giarah": "11",
    "barah": "12",
    "terah": "13", "tera": "13",
    "chaudah": "14", "choda": "14",
    "pandrah": "15", "pandra": "15",
    "solah": "16", "sola": "16",
    "satrah": "17", "satra": "17",
    "atharah": "18", "athara": "18",
    "unnis": "19", "unees": "19",
    "bees": "20",
    "ikkis": "21", "ikees": "21",
    "baees": "22", "bais": "22",
    "teis": "23", "taees": "23",
    "chaubees": "24", "chobees": "24",
    "pachees": "25", "pachis": "25",
    "chabees": "26", "chabbis": "26",
    "sataees": "27", "sattais": "27",
    "athaees": "28", "atthais": "28",
    "untees": "29", "untis": "29",
    "tees": "30",
    "iktees": "31", "ikteees": "31",

    # English number words transliterated by Urdu STT
    "ون": "1", "ٹو": "2", "تھری": "3", "فور": "4", "فائیو": "5",
    "سکس": "6", "سیون": "7", "ایٹ": "8", "نائن": "9", "ٹین": "10",
    # English ordinals commonly transliterated by Urdu STT.
    "ایٹین": "18", "ایٹینتھ": "18", "ایٹینٹھ": "18",

    # Common Roman-Urdu spellings of "baje". Normalize them to one marker
    # so the clock parser only needs one deterministic form.
    "bajy": "baje", "bajay": "baje", "bajey": "baje", "bjy": "baje",
}

def _normalize_spoken_datetime_text(text: str) -> str:
    """Normalize spoken Urdu/Roman-Urdu date/time vocabulary.

    Examples that normalize into the existing deterministic parser:
      ``نو اگست چھ بجے``            -> ``9 august 6 بجے``
      ``nau august chay bajy``      -> ``9 august 6 baje``
      ``no august chay bajy``       -> ``9 august 6 baje``
      ``9 agast 6 bajay``           -> ``9 august 6 baje``

    ``no`` is intentionally treated as nine ONLY when immediately adjacent
    to a month name. Globally replacing English ``no`` would corrupt normal
    conversation (e.g. ``no appointment``).
    """
    normalized = (text or "").lower().strip()

    # Convert Urdu/Eastern-Arabic digits to ASCII first.
    normalized = normalized.translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    ))

    # Normalize known words. Longest-first prevents overlapping aliases.
    for source in sorted(_URDU_DATETIME_WORDS, key=len, reverse=True):
        normalized = re.sub(
            rf"(?<!\\w){re.escape(source)}(?!\\w)",
            _URDU_DATETIME_WORDS[source],
            normalized,
        )

    # Deepgram can occasionally truncate "August" to Urdu "آگ"/"اگ".
    # Never replace that globally because "آگ" also means fire. Treat it as
    # August ONLY when it sits between a valid day-of-month and an obvious
    # clock expression, e.g. "18 آگ 7 بجے".
    normalized = re.sub(
        r"(?<!\d)(\d{1,2})\s+(?:آگ|اگ)\s+(?=\d{1,2}\s*(?:بجے|baje|am|pm)\b)",
        r"\1 august ",
        normalized,
    )

    # Some STT engines render Roman-Urdu ``nau`` as English-looking ``no``.
    # Interpret that spelling as 9 only when it is clearly being used as a
    # day number next to a month, never as a general word.
    month_alt = "|".join(re.escape(name) for name in _MONTH_NAMES_BY_LENGTH)
    normalized = re.sub(
        rf"\bno\s+(?=(?:{month_alt})\b)",
        "9 ",
        normalized,
    )
    normalized = re.sub(
        rf"\b((?:{month_alt}))\s+no\b",
        r"\1 9",
        normalized,
    )

    # Normalize spacing so downstream regexes don't care about repeated gaps.
    return " ".join(normalized.split())


_MONTH_LIKE_STT_HINTS = re.compile(
    r"(?:"
    r"aug(?:ust|ust|ast|us)?|ag(?:ust|ast|us)?|"
    r"اگ|آگ|اوگ|اگی|آگی"
    r")",
    re.IGNORECASE,
)


def _contains_unresolved_date_hint(lowered: str) -> bool:
    """Return True when the caller appears to have supplied a date/month
    expression that the deterministic parser did not successfully resolve.

    In that case a time-only fallback must NOT silently choose today/tomorrow.
    The caller should be asked to repeat/clarify the date instead.
    """
    if not lowered:
        return False

    if any(month in lowered for month in _MONTH_NAMES_BY_LENGTH):
        return True

    if _MONTH_LIKE_STT_HINTS.search(lowered):
        return True

    # Explicit day/date vocabulary also means the caller intended to give a
    # date, even if an STT corruption kept it from resolving.
    return bool(
        re.search(
            r"\b(?:date|day|tareekh|tarikh)\b|(?:تاریخ|دن)",
            lowered,
            re.IGNORECASE,
        )
    )


def _parse_relative_day(lowered: str, now: datetime) -> Optional[datetime]:
    """Returns a date (time still 00:00) for 'aaj'/'kal'/'parso'/'today'/
    'tomorrow'/a weekday name (Roman or native Urdu script). None if no
    day reference found."""
    if "parso" in lowered or "پرسوں" in lowered:
        return (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    if "kal" in lowered or "tomorrow" in lowered or "کل" in lowered:
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if "aaj" in lowered or "today" in lowered or "آج" in lowered:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    for name, weekday_num in _WEEKDAYS.items():
        if name in lowered:
            days_ahead = (weekday_num - now.weekday()) % 7
            days_ahead = days_ahead or 7  # "Monday" said on a Monday means next Monday, not today
            return (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)

    return None


def _find_month_day_match(lowered: str):
    """Locates an explicit month-day reference and returns
    (month_num, day_num, year_or_None, match_start, match_end), or None.
    Split out from _parse_month_day so parse_appointment_datetime can also
    strip the matched span before clock-time parsing runs — otherwise the
    day-of-month digit itself ('10' in '10 august') gets misread as a bare
    hour by _parse_clock_time, silently overriding the correct default
    (noon) with a wrong guessed time."""
    month_num = None
    month_name = None
    for name in _MONTH_NAMES_BY_LENGTH:
        name_match = re.search(rf"\b{name}\b", lowered)
        if name_match:
            month_num = _MONTHS[name]
            month_name = name
            break
    if month_num is None:
        return None

    # day number can come before or after the month name: "10 august" or
    # "august 10", optionally with an ordinal suffix ("10th august")
    pattern = rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s*{month_name}|{month_name}\s*(\d{{1,2}})(?:st|nd|rd|th)?)"
    m = re.search(pattern, lowered)
    if not m:
        return None
    day_num = int(m.group(1) or m.group(2))
    if not (1 <= day_num <= 31):
        return None

    start, end = m.span()
    year = None
    year_m = re.search(r"\b(\d{4})\b", lowered[end:end + 8]) or re.search(r"\b(\d{4})\b", lowered)
    if year_m:
        year = int(year_m.group(1))
        # extend the stripped span to also cover the year if it directly
        # follows the date (e.g. "10 august 2026")
        if lowered[end:end + 8].strip().startswith(year_m.group(1)):
            end = end + lowered[end:end + 8].index(year_m.group(1)) + 4

    return month_num, day_num, year, start, end


def _parse_month_day(lowered: str, now: datetime) -> Optional[datetime]:
    """Returns a date (time still 00:00) for explicit month-day phrasing:
    'august 10', '10 august', '10th august', 'aug 10', with or without a
    year ('10 august 2026'). Tried after _parse_relative_day finds nothing,
    since explicit dates like this are unambiguous and don't need a
    relative-day keyword at all.

    Year defaults to the current year, rolled to next year if that date has
    already passed this year — a customer saying "10 August" in December
    means next August, not one that's already gone."""
    found = _find_month_day_match(lowered)
    if found is None:
        return None
    month_num, day_num, year, _, _ = found
    year = year or now.year

    try:
        candidate = now.replace(year=year, month=month_num, day=day_num,
                                 hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return None  # invalid day for that month (e.g. 31 Feb)

    if found[2] is None and candidate.date() < now.date():
        # no explicit year given and the date's already passed this year
        candidate = candidate.replace(year=year + 1)

    return candidate


def _parse_clock_time(lowered: str) -> Optional[tuple]:
    """Returns (hour_24, minute) or None. Handles '5 baje', '5:30 baje',
    '10 AM', '6 PM'.

    Root cause of a previous bug ("...ki August 10 ki 12 pm baje ki
    appointment...", with a budget "3 crore" and "Phase 6" earlier in the
    sentence, wrongly parsed as 15:00 instead of 12:00): the old regex made
    the period marker (baje/am/pm) fully OPTIONAL on the same match, so
    `re.search` grabbed the leftmost bare digit anywhere in the string —
    here, the "3" from "3 crore" — as "the hour", regardless of whether any
    time marker was actually near it. Then AM/PM resolution searched the
    *entire string* for "pm"/"shaam"/etc., so the "pm" attached to the
    real, later time ("12 pm") leaked onto that unrelated leading "3"
    instead: hour=3 + is_pm_word=True (found elsewhere) = 15:00.

    Fixed by requiring the match to carry its own explicit marker (baje /
    am / pm / a.m. / p.m.) or an explicit ':MM' minute component — a bare,
    unmarked digit is never treated as a time on its own. AM/PM is then
    resolved only from words in the immediate neighbourhood of THAT
    specific match, not the whole sentence, so a marker on some other
    number can no longer leak onto it. The bare-hour default (1-7 -> PM,
    8-11 -> AM) still applies, but only to resolve ambiguity within a
    match that's already confirmed to be a time (has 'baje' with no
    explicit period word) — it no longer decides whether something is a
    time reference at all."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(baje|بجے|a\.m\.|p\.m\.|am|pm)\b", lowered)
    if m is None:
        # no marker anywhere, but an explicit ':MM' is unambiguous enough
        # on its own to count as a time reference (e.g. "5:30")
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)
    if m is None:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    # AM/PM resolved only from local context around this specific match,
    # not the whole sentence, so an unrelated marker can't leak in.
    # شام (evening) / رات (night) / صبح (morning) alongside the existing
    # Roman words - "دوپہر" (dopeher/afternoon) deliberately excluded from
    # is_pm_word: it commonly means the early-afternoon hours (12-4pm)
    # which the existing 1-7->PM bare-hour default already covers
    # correctly without needing an explicit period word at all.
    start, end = m.span()
    context = lowered[max(0, start - 20):end + 20]
    is_pm_word = bool(re.search(r"\bpm\b|p\.m\.|shaam|raat|evening|night|شام|رات", context))
    is_am_word = bool(re.search(r"\bam\b|a\.m\.|subah|morning|صبح", context))

    if hour <= 12:
        if is_pm_word and hour != 12:
            hour += 12
        elif is_am_word and hour == 12:
            hour = 0
        elif not is_pm_word and not is_am_word:
            # no explicit period given — default assumption documented above
            if 1 <= hour <= 7:
                hour += 12
    return hour, minute


def _find_all_relative_day_matches(lowered: str, now: datetime) -> list:
    """Like _parse_relative_day but returns every relative-day reference
    found, not just the first — needed so a reschedule sentence that
    mentions two different days (the original appointment's day and the
    newly requested one) doesn't lose one of them. Each entry is
    (date_at_midnight, start, end)."""
    matches = []

    # Roman/English relative-day words.
    for pattern, delta_days in (
        (r"\bparso\b", 2),
        (r"\b(?:kal|tomorrow)\b", 1),
        (r"\b(?:aaj|today)\b", 0),
    ):
        for m in re.finditer(pattern, lowered):
            date = (now + timedelta(days=delta_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            matches.append((date, m.start(), m.end()))

    # Native Urdu script. Avoid \b here: Python's word-boundary behavior at
    # Arabic-script edges is not reliable enough for these short tokens.
    for token, delta_days in (("پرسوں", 2), ("کل", 1), ("آج", 0)):
        start = 0
        while True:
            pos = lowered.find(token, start)
            if pos < 0:
                break
            date = (now + timedelta(days=delta_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            matches.append((date, pos, pos + len(token)))
            start = pos + len(token)
    for name, weekday_num in _WEEKDAYS.items():
        for m in re.finditer(rf"\b{name}\b", lowered):
            days_ahead = (weekday_num - now.weekday()) % 7
            days_ahead = days_ahead or 7
            date = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
            matches.append((date, m.start(), m.end()))
    matches.sort(key=lambda r: r[1])
    return matches


def _find_all_month_day_matches(lowered: str, now: datetime) -> list:
    """Like _find_month_day_match but returns every explicit month-day
    reference in the text, resolved to a date (year defaulted/rolled the
    same way _parse_month_day does). Unlike _find_month_day_match, the year
    lookahead only checks the text immediately following THIS match, never
    the whole string — with two dates in one sentence, a year written near
    one must never get attributed to the other. Each entry is
    (date_at_midnight, start, end)."""
    results = []
    for name in _MONTH_NAMES_BY_LENGTH:
        pattern = rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s*\b{name}\b|\b{name}\b\s*(\d{{1,2}})(?:st|nd|rd|th)?)"
        for m in re.finditer(pattern, lowered):
            day_num = int(m.group(1) or m.group(2))
            if not (1 <= day_num <= 31):
                continue
            start, end = m.span()
            year = None
            year_m = re.match(r"\s*(\d{4})\b", lowered[end:end + 8])
            if year_m:
                year = int(year_m.group(1))
                end = end + year_m.end()

            month_num = _MONTHS[name]
            y = year or now.year
            try:
                candidate = now.replace(year=y, month=month_num, day=day_num,
                                         hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                continue
            if year is None and candidate.date() < now.date():
                candidate = candidate.replace(year=y + 1)
            results.append((candidate, start, end))
    results.sort(key=lambda r: r[1])
    return results


def _find_all_clock_matches(lowered: str) -> list:
    """Like _parse_clock_time but returns every clock-time reference found
    (same marker-required rule and same local-context AM/PM resolution per
    match, both load-bearing per the bug this file already documents — see
    _parse_clock_time's docstring). Each entry is (hour_24, minute, start, end)."""
    results = []
    seen_spans = set()
    for m in re.finditer(
        r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(baje|بجے|a\.m\.|p\.m\.|am|pm)(?!\w)",
        lowered,
    ):
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        start, end = m.span()
        context = lowered[max(0, start - 20):end + 20]
        is_pm_word = bool(
            re.search(r"\bpm\b|p\.m\.|shaam|raat|evening|night|شام|رات", context)
        )
        is_am_word = bool(
            re.search(r"\bam\b|a\.m\.|subah|morning|صبح", context)
        )
        if hour <= 12:
            if is_pm_word and hour != 12:
                hour += 12
            elif is_am_word and hour == 12:
                hour = 0
            elif not is_pm_word and not is_am_word:
                if 1 <= hour <= 7:
                    hour += 12
        results.append((hour, minute, start, end))
        seen_spans.add((start, end))

    for m in re.finditer(r"\b(\d{1,2}):(\d{2})\b", lowered):
        if m.span() in seen_spans:
            continue
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            results.append((hour, minute, m.start(), m.end()))

    results.sort(key=lambda r: r[2])
    return results


_MAX_DAY_TO_CLOCK_GAP_CHARS = 40  # how close a clock time must sit to a day reference to be treated as "that day's time" rather than an unrelated leftover


def parse_reschedule_datetime(customer_text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Reschedule-specific variant of parse_appointment_datetime(). For a
    plain single-date reschedule ("kal 5 baje reschedule kar dein") this
    returns exactly what parse_appointment_datetime() would.

    The difference is sentences that mention TWO dates — the original
    appointment being referenced and the new one being requested, e.g.
    "Meri August 1 ki 10 baje ki appointment ko August 7 ko 12 baje
    reschedule kar dein." parse_appointment_datetime() has no way to tell
    those apart and grabs whichever comes first (the OLD date), which would
    silently reschedule to the wrong time.

    Heuristic: when multiple date/time mentions are found, the LAST one in
    the sentence is treated as the requested new time. Natural Urdu/English
    phrasing states the new time right before the "reschedule kar dein" /
    "change kar do" verb at the end of the sentence; a mentioned old time
    comes first, as context being referenced. This isn't foolproof for
    unusual phrasing that states the new time first — but per this file's
    own "flag missing data rather than approximate" rule, callers should
    always read back the resolved date/time for confirmation before
    finalizing a reschedule, which catches a misread here same as it would
    catch any other misheard date."""
    now = now or datetime.now()
    lowered = _normalize_spoken_datetime_text(customer_text)

    day_matches = sorted(
        _find_all_relative_day_matches(lowered, now) + _find_all_month_day_matches(lowered, now),
        key=lambda r: r[1],
    )
    clock_matches = _find_all_clock_matches(lowered)

    if not day_matches and not clock_matches:
        return None

    used_clock_idx = set()
    mentions = []  # (resolved_datetime, position)

    for day_dt, d_start, d_end in day_matches:
        best_idx, best_dist = None, None
        for i, (_, _, c_start, c_end) in enumerate(clock_matches):
            if i in used_clock_idx:
                continue
            dist = (c_start - d_end) if c_start >= d_end else (d_start - c_end)
            if dist < 0:
                continue
            if best_dist is None or dist < best_dist:
                best_idx, best_dist = i, dist
        if best_idx is not None and best_dist <= _MAX_DAY_TO_CLOCK_GAP_CHARS:
            hour, minute, c_start, _ = clock_matches[best_idx]
            used_clock_idx.add(best_idx)
            mentions.append((day_dt.replace(hour=hour, minute=minute), min(d_start, c_start)))
        else:
            mentions.append((day_dt.replace(hour=_DEFAULT_HOUR_IF_NO_TIME_GIVEN), d_start))

    for i, (hour, minute, c_start, _) in enumerate(clock_matches):
        if i in used_clock_idx:
            continue
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < now:
            candidate += timedelta(days=1)
        mentions.append((candidate, c_start))

    if not mentions:
        return None

    mentions.sort(key=lambda r: r[1])
    return mentions[-1][0]


def parse_appointment_datetime(customer_text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort parse of a spoken date/time reference into a datetime.
    Returns None if neither a day reference nor a clock time is found at
    all — conversation_agent.py should treat that as "still need the
    date/time" and ask, never book on a guess.

    Day resolution order: relative day word (aaj/kal/parso/weekday) first,
    then an explicit month-day ("10 August" / "August 10"). If neither is
    present but a clock time is (e.g. a bare "10 pm" as a follow-up to an
    agent asking "what time works?"), the day defaults to today, rolled to
    tomorrow if that time has already passed — documented assumption, not
    a silent guess, same spirit as _parse_clock_time's AM/PM default."""
    now = now or datetime.now()
    lowered = _normalize_spoken_datetime_text(customer_text)
    lowered_for_clock = lowered

    day = _parse_relative_day(lowered, now)
    if day is None:
        day = _parse_month_day(lowered, now)
        if day is not None:
            # strip the matched date span so its digits (e.g. the "10" in
            # "10 august") can't also be misread as a bare clock hour
            match = _find_month_day_match(lowered)
            if match is not None:
                _, _, _, start, end = match
                lowered_for_clock = lowered[:start] + " " + lowered[end:]

    clock = _parse_clock_time(lowered_for_clock)

    if day is None:
        if clock is None:
            return None

        # If the caller clearly tried to say a date/month but we could not
        # resolve it, DO NOT silently turn the time into today/tomorrow.
        # Example from live STT:
        #   "اٹھارہ آگیسٹ سات بجے"
        # If "آگیسٹ" were not understood, the old behavior became tomorrow
        # at 7 PM. Returning None is safer: booking asks for the date again.
        if _contains_unresolved_date_hint(lowered):
            return None

        # Genuine time-only follow-up ("7 baje") remains supported.
        hour, minute = clock
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < now:
            candidate += timedelta(days=1)
        return candidate

    if clock is None:
        return day.replace(hour=_DEFAULT_HOUR_IF_NO_TIME_GIVEN)

    hour, minute = clock
    return day.replace(hour=hour, minute=minute)


if __name__ == "__main__":
    samples = [
        "Kal 5 baje appointment book karna hai.",
        "Parso shaam 6 baje visit fix kar dein.",
        "Mera appointment cancel kar dein please.",
        "Waqt change karna hai, kisi aur din milte hain.",
        "Monday 10 AM theek hai kya?",
        "Aaj hi mil sakte hain kya?",
        "10 pm theek hai.",
        "August 10 ko milte hain.",
        "10 August ko theek hai.",
        "10th August shaam 6 baje.",
        "25 December theek hai kya?",
        "Assalam o Alaikum. Mera naam Ali Amir hai. Mera budget 3 crore hai. "
        "Mujhe DHA Phase 6 ki August 10 ki 12 pm baje ki appointment book karni hai.",
    ]
    for s in samples:
        intent = detect_appointment_intent(s)
        dt = parse_appointment_datetime(s)
        print(f"{s!r}\n  intent={intent}, datetime={dt}\n")