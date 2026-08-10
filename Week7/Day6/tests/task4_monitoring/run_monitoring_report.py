from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
OUTPUT = HERE / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import monitoring


def markdown_report(summary: Dict[str, Any], failures) -> str:
    voice = summary["voice_quality"]
    booking = summary["booking_success"]
    rag = summary["rag"]

    lines = [
        "# Week 7 — Day 6 — Task 4 Monitoring Report",
        "",
        f"**Window:** Last {summary['window_minutes']} minutes  ",
        f"**Generated:** `{summary['generated_at']}`",
        "",
        "## Monitoring Summary",
        "",
        "| Required Metric | Current Value |",
        "|---|---:|",
        f"| Average latency | {summary['average_latency_ms']} ms |",
        (
            f"| Voice quality — average STT confidence | "
            f"{voice['average_stt_confidence']} |"
        ),
        (
            f"| Voice quality — TTS success rate | "
            f"{voice['tts_success_rate_percent']}% |"
        ),
        (
            f"| Voice quality — average TTS first-byte latency | "
            f"{voice['average_tts_first_byte_ms']} ms |"
        ),
        f"| API failures | {summary['api_failures']} |",
        f"| Calendar failures | {summary['calendar_failures']} |",
        f"| Email failures | {summary['email_failures']} |",
        (
            f"| Booking success | {booking['successful']}/"
            f"{booking['attempts']} ({booking['rate_percent']}%) |"
        ),
        (
            f"| RAG misses | {rag['misses']}/{rag['queries']} "
            f"({rag['miss_rate_percent']}%) |"
        ),
        "",
        "## Details",
        "",
        f"- Turns monitored: **{summary['turns_monitored']}**",
        f"- Average API latency: **{summary['average_api_latency_ms']} ms**",
        (
            f"- TTS requests: **{voice['tts_successful']}/"
            f"{voice['tts_total']} successful**"
        ),
        f"- Booking failures: **{booking['failed']}**",
        f"- RAG queries: **{rag['queries']}**",
        f"- RAG misses: **{rag['misses']}**",
        "",
        "## Recent Failure / Miss Events",
        "",
    ]

    if not failures:
        lines.append("_No recent failure or miss events were recorded._")
    else:
        lines += [
            "| Time | Session | Metric | Status | Metadata |",
            "|---|---|---|---|---|",
        ]
        for item in failures:
            metadata = json.dumps(
                item.get("metadata") or {},
                ensure_ascii=False,
            ).replace("|", "\\|")
            lines.append(
                f"| {item.get('created_at')} | "
                f"{item.get('session_id') or '-'} | "
                f"`{item.get('metric_name')}` | "
                f"{item.get('status')} | `{metadata}` |"
            )

    lines += [
        "",
        "## What Is Being Monitored",
        "",
        "- **Average latency:** every LangGraph turn through `record_graph_turn()`.",
        "- **Voice quality:** Deepgram STT confidence, Fish TTS first-byte latency, and TTS success/failure.",
        "- **API failures:** provider/API errors through `record_api_request()` or `record_api_failure()`.",
        "- **Calendar failures:** explicit monitoring events and existing `calendar_failed` CRM events.",
        "- **Email failures:** explicit monitoring events and existing `email_failed` CRM events.",
        "- **Booking success:** successful bookings from monitoring events or `appointment_history` compared with failed booking/calendar attempts.",
        "- **RAG misses:** retrieval turns where the RAG layer returns zero hits.",
    ]

    return "\n".join(lines)


def display_terminal(summary: Dict[str, Any]) -> None:
    voice = summary["voice_quality"]
    booking = summary["booking_success"]
    rag = summary["rag"]

    print("=" * 72)
    print("WEEK 7 — DAY 6 — TASK 4: MONITORING")
    print("=" * 72)
    print(f"Window                    : last {summary['window_minutes']} minutes")
    print(f"Turns monitored           : {summary['turns_monitored']}")
    print(f"Average latency           : {summary['average_latency_ms']} ms")
    print(f"Average API latency       : {summary['average_api_latency_ms']} ms")
    print("-" * 72)
    print("VOICE QUALITY")
    print(
        f"  Average STT confidence  : "
        f"{voice['average_stt_confidence']}"
    )
    print(
        f"  TTS success             : "
        f"{voice['tts_successful']}/{voice['tts_total']} "
        f"({voice['tts_success_rate_percent']}%)"
    )
    print(
        f"  Avg TTS first byte      : "
        f"{voice['average_tts_first_byte_ms']} ms"
    )
    print("-" * 72)
    print(f"API failures              : {summary['api_failures']}")
    print(f"Calendar failures         : {summary['calendar_failures']}")
    print(f"Email failures            : {summary['email_failures']}")
    print(
        f"Booking success           : "
        f"{booking['successful']}/{booking['attempts']} "
        f"({booking['rate_percent']}%)"
    )
    print(
        f"RAG misses                : "
        f"{rag['misses']}/{rag['queries']} "
        f"({rag['miss_rate_percent']}%)"
    )
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=60,
        help="Monitoring time window in minutes (default: 60)",
    )
    parser.add_argument(
        "--db",
        help="Optional path to monitoring/knowledge_base.db",
    )
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
        if not db_path.is_absolute():
            db_path = ROOT / db_path
        monitoring.DB_PATH = str(db_path)
        monitoring._READY = False

    summary = monitoring.get_summary(
        window_minutes=args.window_minutes
    )
    failures = monitoring.get_recent_failures(
        window_minutes=args.window_minutes
    )

    display_terminal(summary)

    json_path = OUTPUT / "monitoring_summary.json"
    md_path = OUTPUT / "monitoring_summary.md"

    payload = {
        "summary": summary,
        "recent_failures": failures,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(
        markdown_report(summary, failures),
        encoding="utf-8",
    )

    print()
    print("REPORT FILES:")
    print(f"  JSON: {json_path}")
    print(f"  MD  : {md_path}")


if __name__ == "__main__":
    main()
