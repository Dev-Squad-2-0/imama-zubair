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
    "reschedule", "time change", "waqt tabdeel", "aage kar do", "date change",
    "time badal", "waqt badal", "kisi aur din", "kisi aur waqt",
    "ری شیڈول", "وقت تبدیل", "آگے کر دیں", "تاریخ تبدیل", "وقت بدل",
    "کسی اور دن", "کسی اور وقت",
]
_BOOK_KEYWORDS = [
    "book kar", "book ker", "appointment book", "visit book", "book karna",
    "schedule kar", "visit fix", "milna chahta", "milna chahti", "site visit",
    "appointment lena", "appointment chahiye",
    "بک کر", "اپوائنٹمنٹ بک", "وزٹ بک", "بک کرنا", "شیڈول کر", "وزٹ فکس",
    "ملنا چاہتی", "ملنا چاہتا", "سائٹ وزٹ", "اپوائنٹمنٹ لینا", "اپوائنٹمنٹ چاہیے",
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
    for pattern, delta_days in ((r"\bparso\b", 2), (r"\b(?:kal|tomorrow)\b", 1), (r"\b(?:aaj|today)\b", 0)):
        for m in re.finditer(pattern, lowered):
            date = (now + timedelta(days=delta_days)).replace(hour=0, minute=0, second=0, microsecond=0)
            matches.append((date, m.start(), m.end()))
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
    lowered = customer_text.lower()

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
    lowered = customer_text.lower()
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