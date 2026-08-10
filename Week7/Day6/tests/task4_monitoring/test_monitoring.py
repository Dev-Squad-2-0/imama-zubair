import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import monitoring


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        monitoring.DB_PATH = str(
            Path(self.tmp.name) / "monitoring_test.db"
        )
        monitoring._READY = False

        conn = sqlite3.connect(monitoring.DB_PATH)
        conn.execute(
            """
            CREATE TABLE crm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                event_type TEXT,
                status TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE appointment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                status TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_tracks_required_metrics(self):
        monitoring.record_graph_turn("s1", 1200)
        monitoring.record_graph_turn("s1", 800)
        monitoring.record_voice_quality(
            "s1",
            stt_confidence=0.90,
            tts_first_byte_ms=250,
            tts_success=True,
        )
        monitoring.record_api_failure(
            "Groq",
            "429 rate limit",
            session_id="s1",
        )
        monitoring.record_calendar_result(
            "s1",
            False,
            operation="book",
            error="calendar unavailable",
        )
        monitoring.record_email_result(
            "s1",
            False,
            error="SMTP/API failure",
        )
        monitoring.record_booking_result(
            "s1",
            True,
            event_id="event-1",
        )
        monitoring.record_rag_result("s1", 0)

        summary = monitoring.get_summary(60)

        self.assertEqual(summary["average_latency_ms"], 1000.0)
        self.assertEqual(
            summary["voice_quality"]["average_stt_confidence"],
            0.9,
        )
        self.assertEqual(summary["api_failures"], 1)
        self.assertEqual(summary["calendar_failures"], 1)
        self.assertEqual(summary["email_failures"], 1)
        self.assertEqual(
            summary["booking_success"]["rate_percent"],
            100.0,
        )
        self.assertEqual(summary["rag_misses"], 1)

    def test_voice_quality_tracks_tts_failure(self):
        monitoring.record_voice_quality(
            "s2",
            tts_success=False,
        )
        summary = monitoring.get_summary(60)
        self.assertEqual(
            summary["voice_quality"]["tts_success_rate_percent"],
            0.0,
        )

    def test_rag_hit_is_not_miss(self):
        monitoring.record_rag_result("s3", 3)
        summary = monitoring.get_summary(60)
        self.assertEqual(summary["rag"]["queries"], 1)
        self.assertEqual(summary["rag"]["misses"], 0)

    def test_recent_failures_return_metadata(self):
        monitoring.record_api_failure(
            "Gemini",
            "404 model unavailable",
            session_id="s4",
            operation="tool_call",
        )
        failures = monitoring.get_recent_failures(60)
        self.assertTrue(failures)
        self.assertEqual(
            failures[0]["metadata"]["provider"],
            "Gemini",
        )


if __name__ == "__main__":
    unittest.main()
