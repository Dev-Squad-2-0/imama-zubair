from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = ROOT / "src"
OUTPUT = HERE / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rag_accuracy import evaluate_rag_accuracy
from task3_metrics import (
    booking_success_metrics,
    conversation_success_metrics,
    hallucination_metrics,
    latency_metrics,
    load_json,
    load_properties_from_db,
    memory_accuracy_metrics,
    tool_failure_metrics,
)


def find_task1_results(explicit: Optional[str]) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            return path
        raise FileNotFoundError(f"Task 1 results not found: {path}")

    candidates = [
        ROOT / "tests" / "task1_evaluation" / "output" / "evaluation_results.json",
        ROOT / "tests" / "task 1 evaluation" / "output" / "evaluation_results.json",
        ROOT / "tests" / "task 1 evaluation suite" / "output" / "evaluation_results.json",
        ROOT / "tests" / "task1 evaluation" / "output" / "evaluation_results.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Last-resort discovery: only under tests/, only exact result filename.
    tests_dir = ROOT / "tests"
    if tests_dir.exists():
        matches = list(tests_dir.rglob("evaluation_results.json"))
        if matches:
            return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]

    raise FileNotFoundError(
        "Could not locate Task 1 evaluation_results.json. "
        "Pass it explicitly with --task1-results PATH."
    )


def resolve_eval_db(payload: Dict[str, Any]) -> Optional[Path]:
    value = (payload.get("summary") or {}).get("evaluation_db")
    if not value:
        return None

    path = Path(value)
    if path.exists():
        return path

    # The Task 1 result may contain an absolute path from an earlier copy/run.
    candidate = ROOT / "tests" / "task1_evaluation" / "output" / path.name
    if candidate.exists():
        return candidate

    matches = list((ROOT / "tests").rglob(path.name)) if (ROOT / "tests").exists() else []
    return matches[0] if matches else None


def result_status(value: Optional[float], higher_is_better=True, threshold=None):
    if value is None:
        return "N/A"
    if threshold is None:
        return "MEASURED"
    if higher_is_better:
        return "PASS" if value >= threshold else "REVIEW"
    return "PASS" if value <= threshold else "REVIEW"


def markdown_report(report: Dict[str, Any]) -> str:
    m = report["metrics"]

    lines = [
        "# Week 7 — Day 6 — Task 3 Performance Evaluation",
        "",
        f"**Run ID:** `{report['run_id']}`  ",
        f"**Task 1 source:** `{report['task1_results']}`",
        "",
        "## Executive Summary",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Mean turn latency | {m['latency']['turn_latency_ms']['mean']} ms |",
        f"| P95 turn latency | {m['latency']['turn_latency_ms']['p95']} ms |",
        f"| Conversation success rate | {m['conversation_success']['success_rate_percent']}% |",
        f"| Booking success rate | {m['booking_success']['booking_success_rate_percent']}% |",
        f"| Tool failures | {m['tool_failures']['tool_failures']} |",
        f"| RAG accuracy@{m['rag_accuracy'].get('top_k', 3)} | "
        f"{m['rag_accuracy'].get('rag_accuracy_percent')}% |",
        f"| Memory accuracy | {m['memory_accuracy']['memory_accuracy_percent']}% |",
        f"| Hallucination rate | {m['hallucination']['hallucination_rate_percent']}% |",
        "",
        "## 1. Latency",
        "",
        "Latency is calculated from the real per-turn timings already recorded by the Task 1 runner.",
        "",
        "| Statistic | Turn latency | Conversation latency |",
        "|---|---:|---:|",
        f"| Mean | {m['latency']['turn_latency_ms']['mean']} ms | "
        f"{m['latency']['conversation_latency_ms']['mean']} ms |",
        f"| P50 | {m['latency']['turn_latency_ms']['median_p50']} ms | "
        f"{m['latency']['conversation_latency_ms']['median_p50']} ms |",
        f"| P95 | {m['latency']['turn_latency_ms']['p95']} ms | "
        f"{m['latency']['conversation_latency_ms']['p95']} ms |",
        f"| Maximum | {m['latency']['turn_latency_ms']['max']} ms | "
        f"{m['latency']['conversation_latency_ms']['max']} ms |",
        "",
        "## 2. Conversation Success Rate",
        "",
        f"- Total conversations: **{m['conversation_success']['total']}**",
        f"- Successful: **{m['conversation_success']['successful']}**",
        f"- Failed: **{m['conversation_success']['failed']}**",
        f"- Success rate: **{m['conversation_success']['success_rate_percent']}%**",
        "",
    ]

    if m["conversation_success"]["failed_scenarios"]:
        lines += [
            "Failed scenarios:",
            "",
            *[
                f"- `{scenario_id}`"
                for scenario_id in m["conversation_success"]["failed_scenarios"]
            ],
            "",
        ]

    lines += [
        "## 3. Booking Success",
        "",
        f"- Booking tests identified: **{m['booking_success']['booking_tests']}**",
        f"- Successful bookings: **{m['booking_success']['successful_bookings']}**",
        f"- Failed bookings: **{m['booking_success']['failed_bookings']}**",
        f"- Booking success rate: **{m['booking_success']['booking_success_rate_percent']}%**",
        "",
        "## 4. Tool Failures",
        "",
        f"- Tool/integration failures detected: **{m['tool_failures']['tool_failures']}**",
        f"- CRM event rows checked: **{m['tool_failures']['crm_event_rows_checked']}**",
    ]

    if m["tool_failures"]["failure_rate_percent"] is not None:
        lines.append(
            f"- Recorded CRM-event failure rate: "
            f"**{m['tool_failures']['failure_rate_percent']}%**"
        )

    if m["tool_failures"]["failures"]:
        lines += ["", "Recorded failures:", ""]
        for failure in m["tool_failures"]["failures"]:
            lines.append(f"- `{failure}`")

    lines += [
        "",
        "## 5. RAG Accuracy",
        "",
        (
            f"RAG retrieval accuracy@{m['rag_accuracy'].get('top_k', 3)}: "
            f"**{m['rag_accuracy'].get('rag_accuracy_percent')}%** "
            f"({m['rag_accuracy'].get('correct', 0)}/"
            f"{m['rag_accuracy'].get('cases', 0)} correct)."
        ),
        "",
        m["rag_accuracy"].get(
            "method",
            "RAG retrieval was evaluated against corpus ground truth.",
        ),
        "",
        "| Case | Expected | Rank | Result |",
        "|---|---|---:|---|",
    ]

    for case in m["rag_accuracy"].get("details", []):
        expected = (
            f"{case.get('expected_source')}/"
            f"{case.get('expected_property_id') or '-'}"
        )
        lines.append(
            f"| `{case.get('document_id')}` | {expected} | "
            f"{case.get('matched_rank') or '-'} | "
            f"{'PASS' if case.get('passed') else 'FAIL'} |"
        )

    if m["rag_accuracy"].get("error"):
        lines += ["", f"**RAG evaluation error:** `{m['rag_accuracy']['error']}`"]

    lines += [
        "",
        "## 6. Memory Accuracy",
        "",
        f"- Memory assertions found: **{m['memory_accuracy']['memory_checks']}**",
        f"- Passed: **{m['memory_accuracy']['passed']}**",
        f"- Failed: **{m['memory_accuracy']['failed']}**",
        f"- Memory accuracy: **{m['memory_accuracy']['memory_accuracy_percent']}%**",
        "",
    ]

    if m["memory_accuracy"]["failed_checks"]:
        lines += ["Failed memory checks:", ""]
        for item in m["memory_accuracy"]["failed_checks"]:
            lines.append(
                f"- `{item['scenario_id']}` — {item['label']}"
            )
        lines.append("")

    lines += [
        "## 7. Hallucination Rate",
        "",
        (
            "Hallucination is measured without another LLM judge. Property titles, "
            "prices and bedroom claims in evaluation replies are checked against the "
            "SQLite property database."
        ),
        "",
        f"- Claims checked: **{m['hallucination']['claims_checked']}**",
        f"- Supported claims: **{m['hallucination']['supported_claims']}**",
        f"- Hallucinated/mismatched claims: **{m['hallucination']['hallucinated_claims']}**",
        f"- Hallucination rate: **{m['hallucination']['hallucination_rate_percent']}%**",
        "",
    ]

    hallucinated = [
        c for c in m["hallucination"].get("details", [])
        if c.get("status") == "hallucinated"
    ]
    if hallucinated:
        lines += ["Hallucinated/mismatched claims:", ""]
        for claim in hallucinated:
            lines.append(f"- `{claim}`")
        lines.append("")

    lines += [
        "## Methodology Notes",
        "",
        "- **Latency:** measured from recorded Task 1 turn timings.",
        "- **Conversation success:** Task 1 scenario PASS / total scenarios.",
        "- **Booking success:** booking-success assertions/final booked state from Task 1.",
        "- **Tool failures:** explicit integration errors plus failed CRM-event statuses where available.",
        "- **RAG accuracy:** retriever hit-rate@K against known indexed source documents; no LLM judge.",
        "- **Memory accuracy:** PASS/FAIL of Task 1 checks explicitly testing sticky/carried/remembered context.",
        "- **Hallucination rate:** deterministic structured property claims checked against SQLite ground truth.",
        "",
        "This keeps Task 3 reproducible and avoids spending additional LLM quota merely to score the evaluation.",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task1-results",
        help="Path to Task 1 evaluation_results.json",
    )
    parser.add_argument(
        "--rag-cases",
        type=int,
        default=10,
        help="Maximum number of corpus-grounded RAG retrieval cases (default: 10)",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("WEEK 7 — DAY 6 — TASK 3: PERFORMANCE EVALUATION")
    print("=" * 72)

    task1_path = find_task1_results(args.task1_results)
    print(f"Task 1 results: {task1_path}")

    payload = load_json(task1_path)
    results = payload.get("results") or []

    if not results:
        raise RuntimeError(
            "Task 1 JSON contains no `results`. Run Task 1 first."
        )

    eval_db = resolve_eval_db(payload)
    property_db = ROOT / "db" / "knowledge_base.db"

    print(f"Conversations loaded: {len(results)}")
    print("Measuring latency / conversation / booking / memory...")
    latency = latency_metrics(results)
    conversations = conversation_success_metrics(results)
    booking = booking_success_metrics(results)
    memory = memory_accuracy_metrics(results)

    print("Auditing tool failures...")
    tools = tool_failure_metrics(results, eval_db)

    print("Running deterministic RAG retrieval accuracy probes...")
    rag = evaluate_rag_accuracy(max_cases=args.rag_cases, top_k=3)

    print("Auditing structured property claims for hallucinations...")
    properties = load_properties_from_db(property_db)
    hallucination = hallucination_metrics(results, properties)

    report = {
        "run_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "task1_results": str(task1_path),
        "evaluation_db": str(eval_db) if eval_db else None,
        "property_db": str(property_db),
        "metrics": {
            "latency": latency,
            "conversation_success": conversations,
            "booking_success": booking,
            "tool_failures": tools,
            "rag_accuracy": rag,
            "memory_accuracy": memory,
            "hallucination": hallucination,
        },
    }

    json_path = OUTPUT / "performance_evaluation.json"
    md_path = OUTPUT / "performance_evaluation.md"

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown_report(report), encoding="utf-8")

    print()
    print("=" * 72)
    print("TASK 3 PERFORMANCE EVALUATION COMPLETE")
    print("=" * 72)
    print(
        f"Mean turn latency       : "
        f"{latency['turn_latency_ms']['mean']} ms"
    )
    print(
        f"P95 turn latency        : "
        f"{latency['turn_latency_ms']['p95']} ms"
    )
    print(
        f"Conversation success    : "
        f"{conversations['successful']}/{conversations['total']} "
        f"({conversations['success_rate_percent']}%)"
    )
    print(
        f"Booking success         : "
        f"{booking['successful_bookings']}/{booking['booking_tests']} "
        f"({booking['booking_success_rate_percent']}%)"
    )
    print(f"Tool failures           : {tools['tool_failures']}")
    print(
        f"RAG accuracy@{rag.get('top_k', 3)}         : "
        f"{rag.get('correct', 0)}/{rag.get('cases', 0)} "
        f"({rag.get('rag_accuracy_percent')}%)"
    )
    print(
        f"Memory accuracy         : "
        f"{memory['passed']}/{memory['memory_checks']} "
        f"({memory['memory_accuracy_percent']}%)"
    )
    print(
        f"Hallucination rate      : "
        f"{hallucination['hallucinated_claims']}/"
        f"{hallucination['claims_checked']} "
        f"({hallucination['hallucination_rate_percent']}%)"
    )
    print("-" * 72)

    if conversations["failed_scenarios"]:
        print("Failed conversations:")
        for scenario_id in conversations["failed_scenarios"]:
            print(f"  - {scenario_id}")

    if booking["failed_scenarios"]:
        print("Failed booking tests:")
        for item in booking["failed_scenarios"]:
            print(f"  - {item['id']}: {', '.join(item['failed_checks'])}")

    if memory["failed_checks"]:
        print("Failed memory checks:")
        for item in memory["failed_checks"]:
            print(f"  - {item['scenario_id']}: {item['label']}")

    if tools["failures"]:
        print("Tool failures:")
        for failure in tools["failures"]:
            print(f"  - {failure}")

    print()
    print("REPORT FILES:")
    print(f"  JSON: {json_path}")
    print(f"  MD  : {md_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
