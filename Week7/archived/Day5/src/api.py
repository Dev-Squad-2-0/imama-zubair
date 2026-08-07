"""
Day 5 integration - FastAPI backend.

The capstone brief's required "FastAPI backend with documented endpoints"
deliverable, rebuilt on top of the fixed LangGraph engine (state.py ->
graph.py -> nodes.py) instead of the old conversation_memory-driven
orchestration (moved to old_agent/api.py) - this IS the product now, not a
parallel path alongside it. Owns every provider call (LLM via llm_client.py,
STT/TTS via audio_io.py, Calendar/Gmail/CRM via the modules graph.py's nodes
already call) so app.py (the Streamlit UI) can be a thin HTTP client with no
provider SDKs of its own.

Run with:
    uvicorn api:app --reload --port 8000
(from Day5/src/, or `uvicorn src.api:app --reload --port 8000` from Day5/)

FastAPI's auto-generated docs (GET /docs) cover every endpoint below.
"""

import base64
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import audio_io
import crm_logger
import graph
import graph_logger

app = FastAPI(
    title="RealEstate Hub Voice Agent API",
    description="LangGraph-orchestrated real estate voice agent - text/audio turns, transcripts, execution traces, and turn metrics.",
    version="1.0.0",
)

# The Streamlit UI (app.py) runs as a separate local process/port and calls
# this API over HTTP - CORS has to be open for that to work from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TextTurnRequest(BaseModel):
    text: str


def _trace_tokens(trace: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "prompt_tokens": sum(row.get("prompt_tokens", 0) for row in trace),
        "completion_tokens": sum(row.get("completion_tokens", 0) for row in trace),
        "total_tokens": sum(row.get("total_tokens", 0) for row in trace),
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    """Config sanity check - confirms the env vars each provider needs are
    present. Doesn't call any paid API, just reports what's configured so a
    missing key surfaces immediately instead of on the customer's first turn."""
    return {
        "status": "ok",
        "providers": {
            "llm_primary": bool(os.getenv("BASE_URL") and os.getenv("API_KEY")),
            "llm_gemini_fallback": bool(os.getenv("GEMINI_API_KEY")),
            "deepgram": bool(os.getenv("DEEPGRAM_API_KEY")),
            "fish_audio": bool(os.getenv("FISH_AUDIO_API_KEY")),
            "google_calendar": bool(os.getenv("GOOGLE_CREDENTIALS_PATH")),
        },
    }


@app.post("/session/start")
def start_session() -> Dict[str, Any]:
    """Creates a new session_id and runs the greeting turn. Call this once
    per new call/browser session - graph.py's entry router only greets once
    per session_id even if this is somehow called again for the same id.
    Also synthesizes the greeting's audio (same as a normal /turn/audio
    reply) so a live-call UI can play it immediately instead of opening
    silent - TTS failure here is non-fatal, audio_base64 is just None."""
    session_id = uuid.uuid4().hex
    try:
        agent_reply, trace = graph.run_turn(session_id, "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start session: {e}") from e

    audio_base64 = None
    try:
        reply_audio_bytes, _ = audio_io.synthesize_reply(agent_reply)
        audio_base64 = base64.b64encode(reply_audio_bytes).decode("ascii")
    except RuntimeError:
        pass

    return {"session_id": session_id, "agent_reply": agent_reply, "audio_base64": audio_base64,
            "trace": trace, **_trace_tokens(trace)}


@app.post("/session/{session_id}/turn/text")
def turn_text(session_id: str, req: TextTurnRequest) -> Dict[str, Any]:
    """Runs one turn from plain text (the text-fallback input in the UI, or
    any programmatic caller that already has a transcript)."""
    try:
        agent_reply, trace = graph.run_turn(session_id, req.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Turn failed: {e}") from e
    return {"agent_reply": agent_reply, "trace": trace, **_trace_tokens(trace)}


@app.post("/session/{session_id}/turn/audio")
async def turn_audio(session_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """The push-to-talk endpoint: recorded audio in, spoken reply audio out.
    STT -> graph turn -> TTS, each leg timed; the LangGraph turn itself is
    already timed per-node via graph_logger. Writes one turn_metrics row so
    the UI's logging panel can show stt_ms/tts_ms/total_turn_ms alongside
    the per-node trace."""
    turn_start = time.monotonic()
    audio_bytes = await file.read()
    mimetype = file.content_type or "audio/wav"

    try:
        transcript, stt_ms = audio_io.stt_transcribe(audio_bytes, mimetype=mimetype)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Speech-to-text failed: {e}") from e

    try:
        agent_reply, trace = graph.run_turn(session_id, transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Turn failed: {e}") from e

    try:
        reply_audio_bytes, tts_ms = audio_io.synthesize_reply(agent_reply)
        audio_base64 = base64.b64encode(reply_audio_bytes).decode("ascii")
    except RuntimeError as e:
        # STT + the graph turn already succeeded - the customer's request
        # was understood and acted on, only the spoken reply failed to
        # synthesize. Still return the text reply rather than a bare 502,
        # since the caller (app.py) can fall back to showing text.
        tts_ms = 0
        audio_base64 = None

    total_turn_ms = int((time.monotonic() - turn_start) * 1000)
    tokens = _trace_tokens(trace)
    graph_logger.log_turn_metrics(
        session_id, trace[-1]["turn_id"] if trace else 0,
        stt_ms=stt_ms, tts_ms=tts_ms, total_turn_ms=total_turn_ms, total_tokens=tokens["total_tokens"],
    )

    return {
        "transcript": transcript, "agent_reply": agent_reply, "audio_base64": audio_base64,
        "trace": trace, "stt_ms": stt_ms, "tts_ms": tts_ms, "total_turn_ms": total_turn_ms, **tokens,
    }


@app.get("/session/{session_id}/transcript")
def get_transcript(session_id: str) -> Dict[str, Any]:
    """Full call transcript, oldest first - DB-backed (crm_logger), so it
    survives a backend restart, not just the in-memory session."""
    return {"session_id": session_id, "transcript": crm_logger.get_transcript(session_id)}


@app.get("/session/{session_id}/trace")
def get_trace(session_id: str, turn_id: Optional[int] = None) -> Dict[str, Any]:
    """Full annotated LangGraph execution trace for this session (or one
    turn, if turn_id is given) - node sequence, per-node timing, and token
    usage."""
    return {"session_id": session_id, "trace": graph_logger.get_execution_trace(session_id, turn_id)}


@app.get("/session/{session_id}/metrics")
def get_metrics(session_id: str) -> Dict[str, Any]:
    """Per-turn STT/TTS/total latency + token totals for this session."""
    return {"session_id": session_id, "metrics": graph_logger.get_turn_metrics(session_id)}


@app.get("/session/{session_id}/crm-events")
def get_crm_events(session_id: str) -> Dict[str, Any]:
    """Generic CRM event trail for this session (booked/rescheduled/
    cancelled/email sent/failed/...) - the same crm_events table every
    write-action node's crm_log_tool call writes to."""
    return {"session_id": session_id, "events": crm_logger.get_logs_for_session(session_id)}
