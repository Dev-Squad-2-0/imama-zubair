"""
LangGraph control flow, following the workflow:

FastAPI -> LangGraph
  -> Validate Input
  -> Gather Company Info
  -> Run CrewAI Proposal Team (Research Agent, Solution Architect, Proposal Writer)
  -> Human Approval          (interrupt; graph pauses here)
  -> Generate PDF
  -> Return Download Link

Reuses Day 2's self-correction/retry pattern (retry the crew if the writer's
output doesn't have the required section headers) and Day 3's validation /
graceful-error-handling patterns.
"""
import time
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from crew import run_proposal_crew
from tools import company_lookup
from pdf_gen import generate_proposal_pdf
from logging_config import get_logger, log_event

logger = get_logger()

REQUIRED_SECTIONS = [
    "## Understanding your needs",
    "## Proposed services",
    "## Investment & timeline",
    "## Next steps",
]
MAX_CREW_RETRIES = 2


class OnboardState(TypedDict, total=False):
    company_name: str
    contact_email: str
    project_description: str
    budget_range_usd: str
    timeline_weeks: int

    company_context: Optional[str]
    proposal_text: Optional[str]
    token_usage: Optional[dict]
    crew_attempts: int

    approved: Optional[bool]
    approval_feedback: Optional[str]

    pdf_path: Optional[str]
    status: str
    error: Optional[str]


def validate_input_node(state: OnboardState) -> OnboardState:
    """Failure scenario 1: bad input. Pydantic already validated types at the API
    boundary; here we do the *business* validation that needs domain knowledge."""
    start = time.time()
    errors = []
    if not state.get("company_name", "").strip():
        errors.append("company_name is empty")
    if state.get("timeline_weeks", 0) <= 0:
        errors.append("timeline_weeks must be positive")
    budget = state.get("budget_range_usd", "")
    if "-" not in budget:
        errors.append("budget_range_usd must look like '5000-10000'")

    if errors:
        log_event(logger, "validation_failed", errors=errors, latency_ms=round((time.time() - start) * 1000, 1))
        state["status"] = "failed"
        state["error"] = "Input validation failed: " + "; ".join(errors)
        return state

    log_event(logger, "validation_passed", latency_ms=round((time.time() - start) * 1000, 1))
    state["status"] = "validated"
    return state


def gather_company_info_node(state: OnboardState) -> OnboardState:
    """Failure scenario 2: tool/data-source error. company_lookup already returns
    a graceful 'not found' string rather than raising, but we defensively wrap
    the call anyway in case the JSON file is missing/corrupt."""
    start = time.time()
    try:
        context = company_lookup.func(state["company_name"])
    except Exception as e:  # tool/data-source failure
        log_event(logger, "tool_error", tool="company_lookup", error=str(e))
        context = f"Error: company lookup unavailable ({e}). Proceeding with project description only."

    state["company_context"] = context
    log_event(logger, "company_info_gathered", latency_ms=round((time.time() - start) * 1000, 1))
    return state


def run_crew_node(state: OnboardState) -> OnboardState:
    """Runs the CrewAI proposal team. Self-correction loop: if the writer's
    output is missing required sections (or looks like a refusal), retry up to
    MAX_CREW_RETRIES times before failing gracefully."""
    attempts = state.get("crew_attempts", 0)
    start = time.time()
    try:
        proposal_text, usage = run_proposal_crew(
            company_name=state["company_name"],
            project_description=state["project_description"],
            budget_range_usd=state["budget_range_usd"],
            timeline_weeks=state["timeline_weeks"],
        )
    except Exception as e:
        log_event(logger, "crew_error", attempt=attempts, error=str(e))
        state["crew_attempts"] = attempts + 1
        if state["crew_attempts"] > MAX_CREW_RETRIES:
            state["status"] = "failed"
            state["error"] = f"Crew failed after {MAX_CREW_RETRIES} retries: {e}"
        return state

    latency_ms = round((time.time() - start) * 1000, 1)
    log_event(logger, "crew_completed", attempt=attempts, latency_ms=latency_ms, token_usage=usage)

    # Failure scenario 3: model refusal / degenerate output detection
    refusal_markers = ["i cannot", "i can't help with", "as an ai language model"]
    looks_like_refusal = any(m in proposal_text.lower() for m in refusal_markers)
    missing_sections = [s for s in REQUIRED_SECTIONS if s not in proposal_text]

    state["proposal_text"] = proposal_text
    state["token_usage"] = usage
    state["crew_attempts"] = attempts + 1

    if looks_like_refusal or missing_sections:
        log_event(
            logger, "crew_output_invalid", attempt=attempts,
            missing_sections=missing_sections, looks_like_refusal=looks_like_refusal,
        )
        if state["crew_attempts"] > MAX_CREW_RETRIES:
            state["status"] = "failed"
            state["error"] = (
                f"Proposal output invalid after {MAX_CREW_RETRIES} retries "
                f"(missing sections: {missing_sections})"
            )
        # else: leave status as-is, router will send it back through run_crew_node
        return state

    state["status"] = "crew_ok"
    return state


def crew_router(state: OnboardState):
    if state.get("status") == "failed":
        return "end"
    if state.get("status") == "crew_ok":
        return "approval"
    return "retry"  # missing sections / refusal and retries remain


def human_approval_node(state: OnboardState) -> OnboardState:
    """Human-in-the-loop checkpoint: nothing gets sent to the client until a
    human explicitly approves. Uses LangGraph's interrupt() so the graph
    genuinely pauses and waits for the API layer to resume it."""
    decision = interrupt(
        {
            "type": "approval_required",
            "company_name": state["company_name"],
            "proposal_preview": state["proposal_text"],
        }
    )
    state["approved"] = decision.get("approved", False)
    state["approval_feedback"] = decision.get("feedback")
    log_event(logger, "human_decision", approved=state["approved"])
    return state


def approval_router(state: OnboardState):
    if state.get("approved"):
        return "generate_pdf"
    # rejected -> loop back for a revision pass (bounded by MAX_CREW_RETRIES via crew_attempts)
    if state.get("crew_attempts", 0) > MAX_CREW_RETRIES:
        return "end_rejected"
    return "retry"


def generate_pdf_node(state: OnboardState) -> OnboardState:
    start = time.time()
    try:
        path = generate_proposal_pdf(state["company_name"], state["proposal_text"])
    except Exception as e:
        log_event(logger, "pdf_generation_error", error=str(e))
        state["status"] = "failed"
        state["error"] = f"PDF generation failed: {e}"
        return state

    log_event(logger, "pdf_generated", path=path, latency_ms=round((time.time() - start) * 1000, 1))
    state["pdf_path"] = path
    state["status"] = "completed"
    return state


def build_graph():
    graph = StateGraph(OnboardState)

    graph.add_node("validate_input", validate_input_node)
    graph.add_node("gather_company_info", gather_company_info_node)
    graph.add_node("run_crew", run_crew_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("generate_pdf", generate_pdf_node)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input",
        lambda s: "end" if s.get("status") == "failed" else "continue",
        {"end": END, "continue": "gather_company_info"},
    )
    graph.add_edge("gather_company_info", "run_crew")
    graph.add_conditional_edges(
        "run_crew",
        crew_router,
        {"end": END, "retry": "run_crew", "approval": "human_approval"},
    )
    graph.add_conditional_edges(
        "human_approval",
        approval_router,
        {"generate_pdf": "generate_pdf", "retry": "run_crew", "end_rejected": END},
    )
    graph.add_edge("generate_pdf", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


onboarding_app = build_graph()

print(onboarding_app)


#for the graph
# png = onboarding_app.get_graph().draw_mermaid_png()

# with open("architecture.png", "wb") as f:
#     f.write(png)

# print("architecture.png")