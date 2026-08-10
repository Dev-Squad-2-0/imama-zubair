import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = ROOT / "src"
OUTPUT = HERE / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prompt_injection_suite import SCENARIOS
from runtime import prepare_isolated_runtime
from guardrail_checks import check_turns


RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
SECURITY_TEST_CALLER_PREFIX = os.getenv(
    "SECURITY_TEST_CALLER_PREFIX",
    "03990000",
).strip()


def security_test_caller_id(scenario_id: str) -> str:
    """Return a stable synthetic caller number for this attack.

    A separate phone identity prevents existing CRM preferences/appointments
    for TEST_CALLER_ID from changing security-routing results.
    """
    digits = "".join(ch for ch in scenario_id if ch.isdigit())
    suffix = (digits[-3:] if digits else "000").zfill(3)
    return f"{SECURITY_TEST_CALLER_PREFIX}{suffix}"


def percentile(values, q):
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def run_scenario(graph, scenario, recorder):
    session_id = f"task2-{RUN_ID}-{scenario.id}"
    turns = []
    start_tool_index = recorder.count()
    error = None

    try:
        for index, customer_text in enumerate(scenario.turns, start=1):
            started = time.perf_counter()
            reply, trace_rows = graph.run_turn(
                session_id,
                customer_text,
                caller_id=security_test_caller_id(scenario.id),
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            trace_names = [row["node_name"] for row in trace_rows]

            turns.append({
                "turn": index,
                "customer_text": customer_text,
                "agent_reply": reply,
                "trace": trace_names,
                "latency_ms": elapsed_ms,
            })

            print(
                f"    Turn {index}: "
                f"{' → '.join(trace_names) or '[no trace]'} "
                f"({elapsed_ms}ms)"
            )

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    calls = recorder.since(start_tool_index)

    passed, checks = check_turns(
        scenario,
        turns,
        calls,
    )

    if error:
        checks.append({
            "label": "scenario completed without unhandled exception",
            "status": "FAIL",
            "detail": error,
        })
        passed = False

    return {
        "id": scenario.id,
        "group": scenario.group,
        "description": scenario.description,
        "passed": passed,
        "turns": turns,
        "checks": checks,
        "tool_calls": calls,
        "error": error,
    }


def markdown_report(summary, results):
    passed_results = [r for r in results if r["passed"]]
    failed_results = [r for r in results if not r["passed"]]

    lines = [
        "# Week 7 — Day 6 — Task 2 Prompt Injection Results",
        "",
        "## Overall Summary",
        "",
        f"**Run:** `{summary['run_id']}`  ",
        f"**Total attacks:** {summary['total']}  ",
        f"**Passed:** {summary['passed']}  ",
        f"**Failed:** {summary['failed']}  ",
        f"**Guardrail hold rate:** {summary['guardrail_hold_rate']}%  ",
        f"**Overall status:** **{summary['overall_status']}**  ",
        f"**Write-tool attempts detected:** {summary['write_tool_attempts']}  ",
        f"**Prompt leaks detected:** {summary['prompt_leak_failures']}  ",
        f"**Secret leaks detected:** {summary['secret_leak_failures']}  ",
        "",
        "## Passed Attacks",
        "",
    ]

    if passed_results:
        lines += [
            "| ID | Attack Group | Description |",
            "|---|---|---|",
        ]
        for result in passed_results:
            lines.append(
                f"| `{result['id']}` | "
                f"{result['group'].replace('_', ' ').title()} | "
                f"{result['description']} |"
            )
    else:
        lines.append("_No attacks passed._")

    lines += ["", "## Failed Attacks", ""]

    if failed_results:
        lines += [
            "| ID | Attack Group | Description | Failed Check / Error |",
            "|---|---|---|---|",
        ]
        for result in failed_results:
            reasons = [
                c["label"]
                for c in result["checks"]
                if c["status"] == "FAIL"
            ]
            if result.get("error"):
                reasons.append(result["error"])
            lines.append(
                f"| `{result['id']}` | "
                f"{result['group'].replace('_', ' ').title()} | "
                f"{result['description']} | "
                f"{'; '.join(reasons)} |"
            )
    else:
        lines.append("_No failed attacks._")

    lines += [
        "",
        "## Attack Group Summary",
        "",
        "| Group | Passed | Failed | Total | Hold Rate |",
        "|---|---:|---:|---:|---:|",
    ]

    for group, values in sorted(summary["by_group"].items()):
        lines.append(
            f"| {group.replace('_', ' ').title()} | "
            f"{values['passed']} | {values['failed']} | "
            f"{values['total']} | {values['hold_rate']}% |"
        )

    lines += ["", "## Detailed Results", ""]

    for result in results:
        icon = "PASS" if result["passed"] else "FAIL"
        lines += [
            f"### {icon} — `{result['id']}` — {result['group'].replace('_', ' ').title()}",
            "",
            result["description"],
            "",
        ]

        for turn in result["turns"]:
            lines += [
                f"**Turn {turn['turn']} — Attack:** {turn['customer_text']}",
                "",
                f"**Agent:** {turn['agent_reply']}",
                "",
                f"**Node trace:** `{' → '.join(turn['trace'])}`  ",
                f"**Latency:** {turn['latency_ms']} ms",
                "",
            ]

        if result["tool_calls"]:
            lines += [
                "**Recorded tool calls:**",
                "",
            ]
            for call in result["tool_calls"]:
                lines.append(f"- `{call['tool']}` — `{call['payload']}`")
            lines.append("")

        lines.append("**Guardrail checks:**")
        for check in result["checks"]:
            detail = f" — {check['detail']}" if check.get("detail") else ""
            lines.append(
                f"- {check['status']} — {check['label']}{detail}"
            )

        if result.get("error"):
            lines += ["", f"**Unhandled error:** `{result['error']}`"]

        lines += ["", "---", ""]

    return "\n".join(lines)



def reset_graph_sessions_compat(graph_module):
    """Best-effort in-memory session cleanup across graph.py versions.

    Newer graph.py versions expose SessionStore internally but do not define
    reset_sessions(). Older evaluation code assumed that helper existed.

    Security scenarios already use unique session IDs, so failure to find a
    reset API is harmless; this helper is only hygiene.
    """
    reset_fn = getattr(graph_module, "reset_sessions", None)
    if callable(reset_fn):
        reset_fn()
        print("[security harness] graph sessions reset via reset_sessions()")
        return

    store = getattr(graph_module, "_session_store", None)
    sessions = getattr(store, "_sessions", None) if store is not None else None
    if isinstance(sessions, dict):
        sessions.clear()
        print("[security harness] graph in-memory session store cleared")
        return

    print(
        "[security harness] no global session reset API found; "
        "continuing with unique per-test session IDs"
    )


def main():
    print("=" * 72)
    print("WEEK 7 — DAY 6 — TASK 2: PROMPT INJECTION TESTING")
    print("=" * 72)
    print(f"Run ID: {RUN_ID}")
    print(f"Attacks: {len(SCENARIOS)}")
    print("Calendar/email writes: BLOCKED by security harness")
    print()

    eval_db, recorder = prepare_isolated_runtime(RUN_ID)

    import graph
    reset_graph_sessions_compat(graph)

    results = []

    for index, scenario in enumerate(SCENARIOS, start=1):
        print(
            f"[{index:02d}/{len(SCENARIOS)}] "
            f"{scenario.id} — {scenario.group} — {scenario.description}"
        )
        result = run_scenario(graph, scenario, recorder)
        results.append(result)

        failed_checks = [
            c["label"]
            for c in result["checks"]
            if c["status"] == "FAIL"
        ]

        if result["passed"]:
            print("    RESULT: PASS")
        else:
            print("    RESULT: FAIL")
            for reason in failed_checks:
                print(f"      - {reason}")
        print()

    passed_results = [r for r in results if r["passed"]]
    failed_results = [r for r in results if not r["passed"]]

    groups = defaultdict(lambda: {"passed": 0, "total": 0})
    all_latencies = []

    prompt_leak_failures = 0
    secret_leak_failures = 0
    write_tool_attempts = 0

    for result in results:
        groups[result["group"]]["total"] += 1
        groups[result["group"]]["passed"] += int(result["passed"])

        all_latencies.extend(
            turn["latency_ms"] for turn in result["turns"]
        )

        write_tool_attempts += sum(
            1 for call in result["tool_calls"]
            if call["tool"] in {
                "book_calendar_tool",
                "reschedule_calendar_tool",
                "cancel_calendar_tool",
                "email_tool",
            }
        )

        for check in result["checks"]:
            if (
                check["label"] == "system prompt was not leaked verbatim"
                and check["status"] == "FAIL"
            ):
                prompt_leak_failures += 1
            if (
                check["label"] == "runtime secrets were not disclosed"
                and check["status"] == "FAIL"
            ):
                secret_leak_failures += 1

    passed = len(passed_results)
    failed = len(failed_results)
    total = len(results)

    by_group = {}
    for group, values in groups.items():
        group_failed = values["total"] - values["passed"]
        by_group[group] = {
            "passed": values["passed"],
            "failed": group_failed,
            "total": values["total"],
            "hold_rate": round(
                100 * values["passed"] / values["total"], 2
            ) if values["total"] else 0,
        }

    summary = {
        "run_id": RUN_ID,
        "total": total,
        "passed": passed,
        "failed": failed,
        "guardrail_hold_rate": round(100 * passed / total, 2) if total else 0,
        "overall_status": "PASS" if failed == 0 else "FAIL",
        "write_tool_attempts": write_tool_attempts,
        "prompt_leak_failures": prompt_leak_failures,
        "secret_leak_failures": secret_leak_failures,
        "evaluation_db": str(eval_db),
        "latency_ms": {
            "mean": round(statistics.mean(all_latencies), 2)
            if all_latencies else 0,
            "p50": round(percentile(all_latencies, 0.50), 2),
            "p95": round(percentile(all_latencies, 0.95), 2),
            "max": round(max(all_latencies), 2) if all_latencies else 0,
        },
        "by_group": by_group,
        "passed_attacks": [
            {
                "id": r["id"],
                "group": r["group"],
                "description": r["description"],
            }
            for r in passed_results
        ],
        "failed_attacks": [
            {
                "id": r["id"],
                "group": r["group"],
                "description": r["description"],
                "failed_checks": [
                    c["label"]
                    for c in r["checks"]
                    if c["status"] == "FAIL"
                ],
                "error": r.get("error"),
            }
            for r in failed_results
        ],
    }

    payload = {
        "summary": summary,
        "passed": passed_results,
        "failed": failed_results,
        "results": results,
    }

    json_path = OUTPUT / "prompt_injection_results.json"
    md_path = OUTPUT / "prompt_injection_results.md"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(
        markdown_report(summary, results),
        encoding="utf-8",
    )

    print("=" * 72)
    print("TASK 2 PROMPT INJECTION TESTING COMPLETE")
    print("=" * 72)
    print(f"Overall status       : {summary['overall_status']}")
    print(f"Total attacks        : {total}")
    print(f"Passed               : {passed}")
    print(f"Failed               : {failed}")
    print(f"Guardrail hold rate  : {summary['guardrail_hold_rate']}%")
    print(f"Write-tool attempts  : {write_tool_attempts}")
    print(f"Prompt leaks         : {prompt_leak_failures}")
    print(f"Secret leaks         : {secret_leak_failures}")
    print("-" * 72)

    if passed_results:
        print("\nPASSED ATTACKS:")
        for result in passed_results:
            print(
                f"  [PASS] {result['id']} "
                f"({result['group']}) — {result['description']}"
            )

    if failed_results:
        print("\nFAILED ATTACKS:")
        for result in failed_results:
            reasons = [
                c["label"]
                for c in result["checks"]
                if c["status"] == "FAIL"
            ]
            print(
                f"  [FAIL] {result['id']} "
                f"({result['group']}) — {result['description']}"
            )
            for reason in reasons:
                print(f"         - {reason}")
            if result.get("error"):
                print(f"         - {result['error']}")
    else:
        print("\nFAILED ATTACKS: none")

    print("\nATTACK GROUP SUMMARY:")
    for group, values in sorted(by_group.items()):
        print(
            f"  {group:<22} "
            f"{values['passed']}/{values['total']} passed "
            f"({values['hold_rate']}%)"
        )

    print("\nREPORT FILES:")
    print(f"  JSON: {json_path}")
    print(f"  MD  : {md_path}")
    print("=" * 72)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
