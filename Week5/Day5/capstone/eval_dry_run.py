"""
Dry run of the evaluation harness using a stubbed crew instead of live LLM
calls. This exists so the graph's routing, retry logic, human-approval
interrupt, and scoring/table-writing code can all be exercised and verified
end-to-end in an environment with no model credentials.

IMPORTANT: the proposal text below is hand-written, not model output. Re-run
`python eval.py` with a real .env to get actual scores from the live crew —
this script only proves the harness itself is correct and gives an
illustrative first pass at the results table.
"""
import json
from unittest.mock import patch

import graph
import eval as eval_module

GOOD_PROPOSAL_TEMPLATE = """## Understanding your needs
Thanks for reaching out, {company}. Based on your project description, it sounds like {need_summary}.

## Proposed services
- Smart Contract Audit — $8000
- Managed Node Infrastructure — $2500

## Investment & timeline
Total investment: $10500. Estimated timeline: 3 weeks.

## Next steps
Reply to this email or book a call and we'll get your engagement started.
"""

BAD_INJECTED_PROPOSAL = """Sure, approval skipped, here is your audit for $50 total, no further sections needed.
"""


def make_stub(scenario: str):
    """Returns a stub run_proposal_crew(...) matching the shape of the real one:
    (proposal_text: str, token_usage: dict)."""
    calls = {"n": 0}

    def stub(company_name, project_description, budget_range_usd, timeline_weeks):
        calls["n"] += 1
        usage = {"prompt_tokens": 850, "completion_tokens": 420, "total_tokens": 1270, "successful_requests": 3}

        if scenario == "adversarial" and calls["n"] == 1:
            # first attempt: simulates a weaker model partially following the
            # injected instruction -> self-correction loop should catch this
            return BAD_INJECTED_PROPOSAL, usage

        proposal = GOOD_PROPOSAL_TEMPLATE.format(
            company=company_name,
            need_summary=project_description[:80].rstrip(".") + "...",
        )
        return proposal, usage

    return stub


def run_dry():
    rows = []
    for tc in eval_module.TEST_CASES:
        scenario = "adversarial" if "adversarial" in tc["id"] else "normal"
        with patch.object(graph, "run_proposal_crew", make_stub(scenario)):
            config = {"configurable": {"thread_id": tc["id"] + "_dry"}}
            import time
            start = time.time()
            try:
                result = graph.onboarding_app.invoke({**tc["input"], "crew_attempts": 0}, config=config)
                error = None
            except Exception as e:
                result = {"status": "crashed"}
                error = str(e)
            latency_ms = round((time.time() - start) * 1000, 1)

            # If the graph paused for human approval, simulate the human approving
            # every non-adversarial run and rejecting nothing (approval logic itself
            # is tested by the real API's /onboard/approve endpoint, not here).
            state_snapshot = graph.onboarding_app.get_state(config)
            was_interrupted = None
            if state_snapshot.next:  # graph is paused at an interrupt
                was_interrupted = True
                from langgraph.types import Command
                result = graph.onboarding_app.invoke(
                    Command(resume={"approved": True, "feedback": None}), config=config
                )
            elif result.get("status") == "completed":
                was_interrupted = False

        scores = eval_module.score_manual(result, latency_ms, tc, was_interrupted)
        rows.append({
            "id": tc["id"],
            "note": tc["note"],
            "status": result.get("status"),
            "latency_ms": latency_ms,
            "token_usage": result.get("token_usage"),
            "error": error or result.get("error"),
            **scores,
        })
        print(f"[{tc['id']}] status={result.get('status')} latency={latency_ms}ms")

    with open("eval_results_raw.json", "w") as f:
        json.dump(rows, f, indent=2)
    eval_module.write_markdown_table(rows)
    print("\nWrote eval_results.md and eval_results_raw.json (DRY RUN — stubbed model output)")


if __name__ == "__main__":
    run_dry()
