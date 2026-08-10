import json
import tempfile
import unittest
from pathlib import Path

from task3_metrics import (
    booking_success_metrics,
    conversation_success_metrics,
    latency_metrics,
    memory_accuracy_metrics,
)


SAMPLE = [
    {
        "id": "buyer_04",
        "category": "buyer",
        "passed": False,
        "turns": [
            {"latency_ms": 1000},
            {"latency_ms": 2000},
        ],
        "checks": [
            {
                "label": "second turn still routes to recommendation "
                         "(memory carried budget/area)",
                "status": "FAIL",
            }
        ],
    },
    {
        "id": "appt_01",
        "category": "appointment",
        "passed": True,
        "turns": [{"latency_ms": 500}],
        "checks": [
            {"label": "booking succeeds", "status": "PASS"}
        ],
    },
]


class Task3MetricTests(unittest.TestCase):
    def test_conversation_success(self):
        m = conversation_success_metrics(SAMPLE)
        self.assertEqual(m["total"], 2)
        self.assertEqual(m["successful"], 1)
        self.assertEqual(m["success_rate_percent"], 50.0)

    def test_latency(self):
        m = latency_metrics(SAMPLE)
        self.assertEqual(m["turn_count"], 3)
        self.assertEqual(m["turn_latency_ms"]["mean"], 1166.67)

    def test_booking(self):
        m = booking_success_metrics(SAMPLE)
        self.assertEqual(m["booking_tests"], 1)
        self.assertEqual(m["successful_bookings"], 1)

    def test_memory(self):
        m = memory_accuracy_metrics(SAMPLE)
        self.assertEqual(m["memory_checks"], 1)
        self.assertEqual(m["failed"], 1)


if __name__ == "__main__":
    unittest.main()
