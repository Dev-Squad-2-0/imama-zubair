"""
api.py

Week 6 Day 5, Task 3: Wrap the LangGraph AFL assistant as a FastAPI endpoint.

So we run  it with:
    uvicorn api:app --reload --port 8000

Then POST to /chat:
    curl -X POST http://localhost:8000/chat \
      -H "Content-Type: application/json" \
      -d '{"message": "Who will win Richmond Tigers vs Carlton Blues?", "conversation_id": "demo-1"}'
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

import afl_langgraph_agent as ag

app = FastAPI(title="AFL Assistant API", version="1.0")


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    intent: str
    needs_clarification: bool
    prediction_metadata: Optional[dict] = None
    latency_ms: float
    tools_called: list
    token_usage: Optional[dict] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    out = ag.run_turn(req.message, thread_id=req.conversation_id)

    prediction_metadata = None
    if out.get("intent") == "prediction" and isinstance(out.get("tool_result"), dict):
        prediction_metadata = out["tool_result"]

    return ChatResponse(
        response=out["final_response"],
        intent=out.get("intent") or "unknown",
        needs_clarification=out.get("needs_clarification", False),
        prediction_metadata=prediction_metadata,
        latency_ms=out.get("latency_ms", 0.0),
        tools_called=out.get("tools_called", []),
        token_usage=out.get("token_usage", None)
    )
