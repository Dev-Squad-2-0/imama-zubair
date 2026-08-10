import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from appointment_intent import (
    _normalize_spoken_datetime_text,
    parse_appointment_datetime,
)


NOW = datetime(2026, 8, 9, 19, 19, 0)


class SpokenDateRegressionTests(unittest.TestCase):
    def assert_dt(self, phrase, expected):
        actual = parse_appointment_datetime(phrase, now=NOW)
        self.assertEqual(actual, expected, (phrase, actual))

    def test_bees_ogas_saat_baje(self):
        self.assert_dt(
            "بیس اوگس سات بجے",
            datetime(2026, 8, 20, 19, 0),
        )

    def test_atharah_agist_saat_baje(self):
        self.assert_dt(
            "اٹھارہ آگیسٹ سات بجے",
            datetime(2026, 8, 18, 19, 0),
        )

    def test_atharah_truncated_aag_saat_baje(self):
        self.assert_dt(
            "اٹھارہ آگ سات بجے",
            datetime(2026, 8, 18, 19, 0),
        )

    def test_chaudah_aagast_saat_baje(self):
        self.assert_dt(
            "چودہ آگست سات بجے",
            datetime(2026, 8, 14, 19, 0),
        )

    def test_do_aagast_saat_baje_rolls_next_year_because_date_passed(self):
        self.assert_dt(
            "دو آگست سات بجے",
            datetime(2027, 8, 2, 19, 0),
        )

    def test_plain_time_only_still_works(self):
        # 7 PM already passed on Aug 9 -> genuine time-only fallback is Aug 10.
        self.assert_dt(
            "سات بجے",
            datetime(2026, 8, 10, 19, 0),
        )

    def test_unresolved_month_like_word_does_not_guess_tomorrow(self):
        # Unknown month-like corruption + valid time must ask clarification.
        self.assertIsNone(
            parse_appointment_datetime(
                "اٹھارہ آگیXYZ سات بجے",
                now=NOW,
            )
        )


if __name__ == "__main__":
    unittest.main()
