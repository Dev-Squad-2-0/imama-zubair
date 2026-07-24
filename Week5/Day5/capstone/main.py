"""
FastAPI wrapper around the LangGraph onboarding workflow.

POST /onboard          -> starts a run, returns either a completed result or
                           an "awaiting_approval" status with a thread_id.
POST /onboard/approve   -> resumes a paused run with a human decision.
GET  /onboard/{thread_id}/download -> serves the generated proposal PDF.
"""
import os
import time
import uuid

from dotenv import load_dotenv
load_dotenv()
# CrewAI/LiteLLM reads these standard names, so map our .env vars onto them
# (same pattern as day 3/4 — a custom OpenAI-compatible endpoint, not a hardcoded key)
os.environ["OPENAI_API_KEY"] = os.getenv("API_KEY", "")
os.environ["OPENAI_API_BASE"] = os.getenv("BASE_URL", "")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError

from langgraph.types import Command

from schemas import OnboardRequest, OnboardResponse, ApprovalRequest
from graph import onboarding_app
from logging_config import get_logger, log_event

app = FastAPI(title="Web3Geeks Client Onboarding Agent")
logger = get_logger()


def _state_to_response(thread_id: str, state: dict) -> OnboardResponse:
    status = state.get("status")

    if status == "failed":
        return OnboardResponse(thread_id=thread_id, status="failed", message="Run failed.", error=state.get("error"))

    if status == "completed":
        return OnboardResponse(
            thread_id=thread_id,
            status="completed",
            message="Proposal approved and generated.",
            download_url=f"/onboard/{thread_id}/download",
        )

    # otherwise we're paused at the human_approval interrupt
    return OnboardResponse(
        thread_id=thread_id,
        status="awaiting_approval",
        message="Proposal drafted — awaiting human approval before sending.",
        proposal_preview=state.get("proposal_text"),
    )


@app.post("/onboard", response_model=OnboardResponse)
def onboard(request: OnboardRequest):
    thread_id = str(uuid.uuid4())
    start = time.time()
    log_event(logger, "request_received", thread_id=thread_id, company=request.company_name)

    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "company_name": request.company_name,
        "contact_email": request.contact_email,
        "project_description": request.project_description,
        "budget_range_usd": request.budget_range_usd,
        "timeline_weeks": request.timeline_weeks,
        "crew_attempts": 0,
    }

    try:
        result = onboarding_app.invoke(initial_state, config=config)
    except Exception as e:
        log_event(logger, "unhandled_error", thread_id=thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Agent run failed: {e}")

    latency_ms = round((time.time() - start) * 1000, 1)
    log_event(logger, "request_finished", thread_id=thread_id, latency_ms=latency_ms, status=result.get("status"))
    return _state_to_response(thread_id, result)


@app.post("/onboard/approve", response_model=OnboardResponse)
def approve(decision: ApprovalRequest):
    config = {"configurable": {"thread_id": decision.thread_id}}

    if not decision.approved and not decision.feedback:
        raise HTTPException(status_code=422, detail="feedback is required when rejecting a proposal")

    try:
        result = onboarding_app.invoke(
            Command(resume={"approved": decision.approved, "feedback": decision.feedback}),
            config=config,
        )
    except Exception as e:
        log_event(logger, "unhandled_error", thread_id=decision.thread_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Resume failed: {e}")

    log_event(logger, "approval_processed", thread_id=decision.thread_id, approved=decision.approved)
    return _state_to_response(decision.thread_id, result)


@app.get("/onboard/{thread_id}/download")
def download(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    state = onboarding_app.get_state(config).values
    pdf_path = state.get("pdf_path")
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No PDF available for this thread_id yet")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.split("/")[-1])


@app.get("/health")
def health():
    return {"status": "ok"}
