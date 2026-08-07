"""
Day 4 - appointment intent detection + date/time parsing.

Small, deliberately-scoped companion to objection_handler.py: same
keyword-classification pattern, applied to booking intent instead of
objections. Lives separately from appointment_management.py because that
module is pure action-execution (given a datetime, do the booking) — intent
detection and parsing are a different concern (given raw customer text,
figure out WHAT the customer wants and WHEN).

Honesty note on the parser: this is a best-effort regex parser for common
UrduLish date/time phrasing ("kal 5 baje", "parso shaam 6 baje", "Monday
10 AM"), not a full natural-language date parser. It returns None on
anything it can't confidently parse, and the caller is expected to ask the
customer to clarify rather than guess a time — matching the project's "flag
missing data rather than approximating" rule. Anything genuinely ambiguous
(e.g. a bare "5 baje" with no AM/PM cue) is resolved with a documented
default, not silently guessed differently each time - and both parsing
functions below report whether they had to fall back to that default via
their `had_explicit_clock` return value, so a caller can ask "what time
exactly?" instead of silently booking on a guess.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple


# ---------- Intent detection ----------

_CANCEL_KEYWORDS = [
    "cancel kar", "cancel ker", "appointment cancel", "visit cancel",
    "cancel karna", "cancel krna", "nahi aana ab", "appointment khatam",
]
_RESCHEDULE_KEYWORDS = [
    "reschedule", "time change", "waqt tabdeel", "aage kar do", "date change",
    "time badal", "waqt badal", "kisi aur din", "kisi aur waqt",
]
_BOOK_KEYWORDS = [
    "book kar", "book ker", "appointment book", "visit book", "book karna",
    "schedule kar", "visit fix", "milna chahta", "milna chahti", "site visit",
    "appointment lena", "appointment chahiye",
]


def detect_appointment_intent(customer_text: str) -> Optional[str]:
    """Returns "cancel", "reschedule", "book", or None. Checked in that
    order since "reschedule" phrasing can loosely overlap with "book"
    phrasing ("kisi aur din book karna hai") — cancel and reschedule are
    checked first so they aren't misread as a fresh booking."""
    lowered = customer_text.lower()

    if any(kw in lowered for kw in _CANCEL_KEYWORDS):
        return "cancel"
    if any(kw in lowered for kw in _RESCHEDULE_KEYWORDS):
        return "reschedule"
    if any(kw in lowered for kw in _BOOK_KEYWORDS):
        return "book"
    return None


# ---------- Date/time parsing ----------

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
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


def _find_all_relative_day_matches(lowered: str, now: datetime) -> list:
    """Returns every relative-day reference found in the text (not just the
    first) - needed so a sentence that mentions two different days (e.g. the
    original appointment's day and a newly requested one) doesn't lose
    either of them. Each entry is (date_at_midnight, start, end)."""
    matches = []
    for pattern, delta_days in ((r"\bparso\b", 2), (r"\b(?:kal|tomorrow)\b", 1), (r"\b(?:aaj|today)\b", 0)):
        for m in re.finditer(pattern, lowered):
            date = (now + timedelta(days=delta_days)).replace(hour=0, minute=0, second=0, microsecond=0)
            matches.append((date, m.start(), m.end()))
    for name, weekday_num in _WEEKDAYS.items():
        for m in re.finditer(rf"\b{name}\b", lowered):
            days_ahead = (weekday_num - now.weekday()) % 7
            days_ahead = days_ahead or 7  # "Monday" said on a Monday means next Monday, not today
            date = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
            matches.append((date, m.start(), m.end()))
    matches.sort(key=lambda r: r[1])
    return matches


def _find_all_month_day_matches(lowered: str, now: datetime) -> list:
    """Returns every explicit month-day reference in the text (e.g.
    '10 august', 'august 10th'), resolved to a date - year defaults to the
    current year, rolled to next year if that date's already passed this
    year and no year was stated. The year lookahead only checks the text
    immediately following THIS match, never the whole string - with two
    dates in one sentence, a year written near one must never get
    attributed to the other. Each entry is (date_at_midnight, start, end)."""
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
    """Returns every clock-time reference found in the text. A bare,
    unmarked digit is never treated as a time on its own - the match must
    carry its own explicit marker (baje / am / pm / a.m. / p.m.) or an
    explicit ':MM' minute component, and AM/PM is resolved only from words
    in the immediate neighbourhood of THAT specific match (not the whole
    sentence). This is load-bearing: an earlier version of this parser let
    the period marker be fully optional on the match, so a `re.search` for
    "the hour" could grab an unrelated leading digit elsewhere in the
    sentence (e.g. a budget figure), and AM/PM resolved from anywhere in the
    string could then leak an unrelated marker onto it - producing a wrong
    resolved time from a sentence that also mentioned a marked time
    elsewhere. Each entry is (hour_24, minute, start, end)."""
    results = []
    seen_spans = set()
    for m in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(baje|a\.m\.|p\.m\.|am|pm)\b", lowered):
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        start, end = m.span()
        context = lowered[max(0, start - 20):end + 20]
        is_pm_word = bool(re.search(r"\bpm\b|p\.m\.|shaam|raat|evening|night", context))
        is_am_word = bool(re.search(r"\bam\b|a\.m\.|subah|morning", context))
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


def _resolve_datetime_mentions(lowered: str, now: datetime) -> list:
    """Finds every day/clock-time reference in the text and pairs each day
    mention with its nearest not-yet-used clock mention (within
    _MAX_DAY_TO_CLOCK_GAP_CHARS chars). Shared by parse_appointment_datetime
    and parse_reschedule_datetime - both need "which clock time in this
    sentence actually belongs to which day" resolved the same proximity-
    aware way, since a plain single first-match parse can grab an unrelated
    marked time mentioned elsewhere in the sentence instead of the one that
    actually sits next to the day being talked about (e.g. "abhi 8:30 baje
    hai, kal 12 pm appointment chahiye" - the customer's own current-time
    remark must not get picked over "kal 12 pm").

    Returns a list of (resolved_datetime, position, had_explicit_clock,
    from_day), sorted by position in the sentence.
      - had_explicit_clock=False means a day was understood but no nearby
        clock time was found - the hour was set to the documented default
        (noon), not something the customer actually said, and callers
        should treat that as "still need to ask what time" rather than a
        confirmed value.
      - from_day=True means this mention is anchored to an actual day
        reference (aaj/kal/a weekday/an explicit date) - callers picking
        "the" appointment time out of a sentence with several time mentions
        should prefer these over a bare, day-less clock mention (which may
        just be an aside like "abhi 8:30 baje hai", not a requested time)."""
    day_matches = sorted(
        _find_all_relative_day_matches(lowered, now) + _find_all_month_day_matches(lowered, now),
        key=lambda r: r[1],
    )
    clock_matches = _find_all_clock_matches(lowered)

    if not day_matches and not clock_matches:
        return []

    used_clock_idx = set()
    mentions = []  # (resolved_datetime, position, had_explicit_clock, from_day)

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
            mentions.append((day_dt.replace(hour=hour, minute=minute), min(d_start, c_start), True, True))
        else:
            mentions.append((day_dt.replace(hour=_DEFAULT_HOUR_IF_NO_TIME_GIVEN), d_start, False, True))

    for i, (hour, minute, c_start, _) in enumerate(clock_matches):
        if i in used_clock_idx:
            continue
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < now:
            candidate += timedelta(days=1)
        mentions.append((candidate, c_start, True, False))

    mentions.sort(key=lambda r: r[1])
    return mentions


def parse_reschedule_datetime(customer_text: str, now: Optional[datetime] = None) -> Optional[Tuple[datetime, bool]]:
    """Reschedule-specific variant of parse_appointment_datetime(). For a
    plain single-date reschedule ("kal 5 baje reschedule kar dein") this
    resolves the same mention parse_appointment_datetime() would.

    The difference is sentences that mention TWO dates — the original
    appointment being referenced and the new one being requested, e.g.
    "Meri August 1 ki 10 baje ki appointment ko August 7 ko 12 baje
    reschedule kar dein." A single first-match parse has no way to tell
    those apart and would grab whichever comes first (the OLD date), which
    would silently reschedule to the wrong time.

    Heuristic: when multiple date/time mentions are found, the LAST one in
    the sentence is treated as the requested new time. Natural Urdu/English
    phrasing states the new time right before the "reschedule kar dein" /
    "change kar do" verb at the end of the sentence; a mentioned old time
    comes first, as context being referenced. This isn't foolproof for
    unusual phrasing that states the new time first — but per this file's
    own "flag missing data rather than approximate" rule, callers should
    always read back the resolved date/time for confirmation before
    finalizing a reschedule, which catches a misread here same as it would
    catch any other misheard date.

    Returns (datetime, had_explicit_clock) or None if nothing was found at
    all. had_explicit_clock=False means the day was understood but the hour
    was defaulted (noon), not stated - callers should ask what time rather
    than reschedule on that guess."""
    now = now or datetime.now()
    lowered = customer_text.lower()
    mentions = _resolve_datetime_mentions(lowered, now)
    if not mentions:
        return None
    dt, _, had_explicit_clock, _ = mentions[-1]
    return dt, had_explicit_clock


def parse_appointment_datetime(customer_text: str, now: Optional[datetime] = None) -> Optional[Tuple[datetime, bool]]:
    """Best-effort parse of a spoken date/time reference into a datetime,
    for a fresh booking. Returns None if neither a day reference nor a
    clock time is found at all — callers should treat that as "still need
    the date/time" and ask, never book on a guess.

    Uses the same proximity-aware mention resolver as
    parse_reschedule_datetime() (see _resolve_datetime_mentions). Prefers
    the FIRST day-anchored mention (from_day=True - a mention tied to an
    actual aaj/kal/weekday/explicit-date reference) over any bare, day-less
    clock mention, and only falls back to a bare clock mention (e.g. a
    one-word follow-up like "10 pm theek hai" answering "what time works?")
    if the sentence has no day reference at all. This is what prevents a
    case like "abhi 8:30 baje hai, kal 12 pm appointment chahiye" from
    having the customer's own current-time remark ("8:30", day-less) picked
    over the actually-requested "kal 12 pm" (day-anchored) — a plain
    first-by-position pick would grab whichever marked time appears first
    in the string regardless of whether it's actually tied to a day the
    customer named.

    Returns (datetime, had_explicit_clock) or None. had_explicit_clock=False
    means a day was understood but no clock time could be confidently
    resolved (the hour defaulted to noon) - callers should ask what time
    exactly rather than book on that default."""
    now = now or datetime.now()
    lowered = customer_text.lower()
    mentions = _resolve_datetime_mentions(lowered, now)
    if not mentions:
        return None
    day_anchored = [m for m in mentions if m[3]]
    dt, _, had_explicit_clock, _ = day_anchored[0] if day_anchored else mentions[0]
    return dt, had_explicit_clock


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
        # regression case for the "tomorrow 12pm" bug: an earlier marked time
        # in the sentence (the customer's own "it's 8:30 right now" remark)
        # must NOT be picked over the actually-requested "kal 12 pm".
        "Abhi 8:30 baje hai, kal 12 pm appointment chahiye.",
        # day understood, no time given at all - should report had_explicit_clock=False
        "Kal appointment book karna hai.",
    ]
    for s in samples:
        intent = detect_appointment_intent(s)
        result = parse_appointment_datetime(s)
        if result is None:
            print(f"{s!r}\n  intent={intent}, datetime=None\n")
        else:
            dt, had_explicit_clock = result
            print(f"{s!r}\n  intent={intent}, datetime={dt}, had_explicit_clock={had_explicit_clock}\n")
