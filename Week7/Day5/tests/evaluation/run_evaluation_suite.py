"""
Day 6 - Task 1: Evaluation Suite runner.

Runs every scenario in evaluation_suite.py through the real graph.run_turn()
(no mocking - same convention as the rest of this project's tests), applies
each scenario's checks, and writes:
    eval_results.json  - full transcript/trace/state per scenario, machine-readable
    eval_results.md    - human-readable summary, pass/fail per check, by category

Nothing here is audio - text-only, same reasoning covered earlier: this
suite is about testing reasoning/routing/guardrails, not the voice
pipeline (tests/audio/ covers that separately, at a much smaller scale).

Run from tests/eval/:
    python3 run_evaluation_suite.py
"""

import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import graph  # noqa: E402
from evaluation_suite import ALL_SCENARIOS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_ID = time.strftime("%Y%m%d%H%M%S")


def run_scenario(scenario: dict) -> dict:
    session_id = f"eval-{scenario['id']}-{RUN_ID}"
    result = {
        "id": scenario["id"], "category": scenario["category"],
        "description": scenario["description"], "turns": [],
    }

    all_traces, all_replies = [], []
    try:
        for customer_text in scenario["turns"]:
            reply, trace = graph.run_turn(session_id, customer_text)
            node_names = [t["node_name"] for t in trace]
            all_traces.append(node_names)
            all_replies.append(reply)
            result["turns"].append({
                "customer_text": customer_text, "agent_reply": reply, "trace": node_names,
            })
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["checks"] = [{"label": "scenario completed without an unhandled exception",
                              "status": "FAIL"}]
        return result

    final_state = graph.get_session_state(session_id) or {}
    checks_out = []
    for label, check_fn in scenario.get("checks", []):
        try:
            passed = bool(check_fn(final_state, all_traces, all_replies))
        except Exception as e:
            passed = False
            label = f"{label} (check itself raised {type(e).__name__}: {e})"
        checks_out.append({"label": label, "status": "PASS" if passed else "FAIL"})

    if not checks_out:
        checks_out.append({"label": "scenario ran to completion (no automated assertions for this one - manual transcript review)",
                            "status": "PASS"})

    result["checks"] = checks_out
    result["final_state_summary"] = {
        "call_intent": final_state.get("intent", {}).get("call_intent"),
        "appointment_intent": final_state.get("intent", {}).get("appointment_intent"),
        "appointment_status": final_state.get("appointment_status"),
        "clarification_needed": final_state.get("clarification_needed"),
        "decline_count": final_state.get("decline_count"),
    }
    return result


def main():
    print(f"Running {len(ALL_SCENARIOS)} scenarios (run id: {RUN_ID})...\n")

    results = []
    by_category = defaultdict(lambda: {"pass": 0, "fail": 0})

    for i, scenario in enumerate(ALL_SCENARIOS, 1):
        print(f"[{i}/{len(ALL_SCENARIOS)}] {scenario['id']} ({scenario['category']}): {scenario['description']}")
        result = run_scenario(scenario)
        results.append(result)

        for check in result["checks"]:
            key = "pass" if check["status"] == "PASS" else "fail"
            by_category[scenario["category"]][key] += 1
            marker = "PASS" if check["status"] == "PASS" else "FAIL"
            print(f"    [{marker}] {check['label']}")
        if "error" in result:
            print(f"    ERROR: {result['error']}")

    # ---- write results ----
    json_path = os.path.join(HERE, "eval_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"run_id": RUN_ID, "results": results}, f, ensure_ascii=False, indent=2)

    total_pass = sum(c["pass"] for c in by_category.values())
    total_fail = sum(c["fail"] for c in by_category.values())
    errored = sum(1 for r in results if "error" in r)

    md_path = os.path.join(HERE, "eval_results.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Day 6 Evaluation Suite Results\n\nRun ID: {RUN_ID}\n\n")
        f.write(f"**{len(ALL_SCENARIOS)} scenarios, {total_pass} checks passed, "
                f"{total_fail} checks failed, {errored} scenario(s) errored.**\n\n")
        f.write("## By category\n\n| Category | Passed | Failed |\n|---|---|---|\n")
        for cat, counts in sorted(by_category.items()):
            f.write(f"| {cat} | {counts['pass']} | {counts['fail']} |\n")
        f.write("\n## Full transcripts\n\n")
        for r in results:
            f.write(f"### {r['id']} — {r['category']}: {r['description']}\n\n")
            if "error" in r:
                f.write(f"**ERRORED:** `{r['error']}`\n\n")
                continue
            for turn in r["turns"]:
                f.write(f"- **USER:** {turn['customer_text'] or '(empty/silent)'}\n")
                f.write(f"  **AGENT:** {turn['agent_reply'] or '(empty reply)'}\n")
                f.write(f"  *trace: {' -> '.join(turn['trace'])}*\n\n")
            for check in r["checks"]:
                f.write(f"  - [{check['status']}] {check['label']}\n")
            f.write("\n")

    print(f"\n{'=' * 70}")
    print(f"Summary: {total_pass} passed, {total_fail} failed, {errored} scenario(s) errored, "
          f"{len(ALL_SCENARIOS)} scenarios total")
    print(f"Results: {json_path}")
    print(f"Report:  {md_path}")

    if total_fail or errored:
        sys.exit(1)


if __name__ == "__main__":
    main()
