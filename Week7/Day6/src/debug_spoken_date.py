"""Quick spoken-date parser diagnostic.

Run:
    python debug_spoken_date.py "اٹھارہ آگیسٹ سات بجے"
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from appointment_intent import (
    _normalize_spoken_datetime_text,
    parse_appointment_datetime,
)


text = " ".join(sys.argv[1:]).strip()
if not text:
    raise SystemExit("Usage: python debug_spoken_date.py <spoken date/time>")

print("RAW       :", text)
print("NORMALIZED:", _normalize_spoken_datetime_text(text))
print("PARSED    :", parse_appointment_datetime(text))
