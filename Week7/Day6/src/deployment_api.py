"""Production FastAPI entrypoint for the RealEstate Hub agent.

This wrapper is intentionally thin:
- it calls the CURRENT graph.run_turn() implementation;
- it does not duplicate booking/RAG/security business logic;
- it adds HTTP request handling, structured logging, monitoring, health checks,
  and deployment-friendly startup behavior.

Run locally:
    uvicorn src.deployment_api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
import threading
import time
import uuid
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Current project modules use imports such as `import nodes`, so /src must also
# be importable as a top-level module when this file is loaded as src.*.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from logging_config import (
    configure_logging,
    reset_request_context,
    set_request_context,
)

configure_logging()

logger = logging.getLogger("deployment_api")


def _env_true(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _warm_rag_sync() -> None:
    """Run RAG warmup synchronously during lifespan startup.

    Blocks until the embedding model and Chroma collection are hot.
    This ensures the FIRST real call never pays the cold-start penalty
    (~18 s SentenceTransformer load + ~1 s Chroma open) that would push
    total turn latency past Vapi's 10-second LLM timeout.

    A failure here is logged as a warning but does NOT abort server startup.
    """
    if not _env_true("RAG_WARMUP_ON_API_START", "1"):
        logger.info("RAG background warmup disabled")
        return

    try:
        import rag_pipeline

        warmup = getattr(rag_pipeline, "warmup", None)
        if callable(warmup):
            logger.info("RAG warmup starting (blocking until ready) …")
            result = warmup()
            logger.info("RAG warmup complete: %s", result)
        else:
            rag_pipeline.get_collection()
            logger.info("RAG collection connected during startup warmup")
    except Exception as exc:
        logger.warning("RAG warmup failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting RealEstate Hub API env=%s",
        os.getenv("APP_ENV", "development"),
    )
    # Run warmup in a thread so we don't block the event loop, but
    # await it so startup is complete before accepting requests.
    await run_in_threadpool(_warm_rag_sync)
    yield
    logger.info("Stopping RealEstate Hub API")


app = FastAPI(
    title="RealEstate Hub Voice Agent API",
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
)

app.mount("/crm", StaticFiles(directory=str(ROOT / "crm_dashboard"), html=True), name="crm")


try:
    import monitoring
except Exception:
    monitoring = None


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    tokens = set_request_context(request_id=request_id)

    started = time.perf_counter()
    response = None

    try:
        response = await call_next(request)
        return response

    except Exception as exc:
        logger.exception(
            "Unhandled API exception method=%s path=%s",
            request.method,
            request.url.path,
        )

        if monitoring is not None:
            try:
                monitoring.record_api_failure(
                    provider="fastapi",
                    error=exc,
                    operation=f"{request.method} {request.url.path}",
                )
            except Exception:
                pass
        raise

    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        status_code = getattr(response, "status_code", 500)

        if monitoring is not None:
            try:
                monitoring.record_api_request(
                    request.url.path,
                    request.method,
                    status_code,
                    latency_ms,
                )
            except Exception:
                pass

        logger.info(
            "HTTP request method=%s path=%s status=%s latency_ms=%.2f",
            request.method,
            request.url.path,
            status_code,
            latency_ms,
        )

        if response is not None:
            response.headers["X-Request-ID"] = request_id

        reset_request_context(tokens)


class ConversationTurnRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    customer_text: str = Field(default="", max_length=10000)
    caller_id: Optional[str] = Field(default=None, max_length=64)


class ConversationTurnResponse(BaseModel):
    success: bool
    session_id: str
    agent_reply: str
    trace: list[str]
    latency_ms: float


def _db_health() -> Dict[str, Any]:
    db_path = Path(
        os.getenv(
            "DATABASE_PATH",
            str(ROOT / "db" / "knowledge_base.db"),
        )
    )

    try:
        if not db_path.exists():
            return {
                "ok": False,
                "detail": f"database not found: {db_path}",
            }

        conn = sqlite3.connect(str(db_path), timeout=3)
        conn.execute("SELECT 1").fetchone()
        conn.close()

        return {
            "ok": True,
            "path": str(db_path),
        }
    except Exception as exc:
        return {
            "ok": False,
            "detail": str(exc),
            "path": str(db_path),
        }


def _llm_health() -> Dict[str, Any]:
    configured = {
        "primary": bool(
            os.getenv("BASE_URL")
            and os.getenv("API_KEY")
        ),
        "groq": bool(os.getenv("GROQ_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
    }
    return {
        "ok": any(configured.values()),
        "providers": configured,
    }


def _credential_file_health() -> Dict[str, Any]:
    path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if not path:
        return {
            "ok": False,
            "detail": "GOOGLE_CREDENTIALS_PATH is not set",
        }

    exists = Path(path).exists()
    return {
        "ok": exists,
        "path": path,
        "detail": None if exists else "credential file does not exist",
    }


def _voice_health() -> Dict[str, Any]:
    deepgram = bool(os.getenv("DEEPGRAM_API_KEY"))
    fish = bool(os.getenv("FISH_AUDIO_API_KEY"))

    return {
        "ok": deepgram and fish,
        "deepgram_configured": deepgram,
        "fish_audio_configured": fish,
    }


def _rag_health() -> Dict[str, Any]:
    chroma_path = Path(
        os.getenv(
            "CHROMA_DIR",
            str(ROOT / "db" / "chroma"),
        )
    )
    sqlite_file = chroma_path / "chroma.sqlite3"
    return {
        "ok": chroma_path.exists() and sqlite_file.exists(),
        "path": str(chroma_path),
    }


def health_details() -> Dict[str, Any]:
    database = _db_health()
    llm = _llm_health()
    google_credentials = _credential_file_health()
    voice = _voice_health()
    rag = _rag_health()

    require_calendar = _env_true(
        "REQUIRE_CALENDAR_FOR_READINESS",
        "1",
    )
    require_email = _env_true(
        "REQUIRE_EMAIL_FOR_READINESS",
        "1",
    )
    require_voice = _env_true(
        "REQUIRE_VOICE_FOR_READINESS",
        "0",
    )
    require_rag = _env_true(
        "REQUIRE_RAG_FOR_READINESS",
        "1",
    )

    healthy = database["ok"] and llm["ok"]

    if require_calendar:
        healthy = healthy and google_credentials["ok"]
    if require_email:
        healthy = healthy and google_credentials["ok"]
    if require_voice:
        healthy = healthy and voice["ok"]
    if require_rag:
        healthy = healthy and rag["ok"]

    return {
        "healthy": bool(healthy),
        "environment": os.getenv("APP_ENV", "development"),
        "checks": {
            "database": database,
            "llm": llm,
            "google_credentials": google_credentials,
            "voice": voice,
            "rag": rag,
        },
        "required_for_readiness": {
            "calendar": require_calendar,
            "email": require_email,
            "voice": require_voice,
            "rag": require_rag,
        },
    }


@app.get("/")
async def root():
    return {
        "service": "RealEstate Hub Voice Agent API",
        "status": "running",
        "health": "/health/ready",
        "docs": "/docs",
    }


@app.get("/health/live")
async def health_live():
    # Liveness answers only "is this process alive?"
    return {
        "status": "ok",
        "service": "realestate-voice-agent",
    }


@app.get("/health/ready")
async def health_ready():
    details = health_details()
    return JSONResponse(
        status_code=200 if details["healthy"] else 503,
        content=details,
    )


@app.get("/health")
async def health():
    return health_details()


@app.get("/metrics/summary")
async def metrics_summary(window_minutes: int = 60):
    window_minutes = max(1, min(window_minutes, 10080))

    if monitoring is None:
        return JSONResponse(
            status_code=503,
            content={
                "available": False,
                "detail": "monitoring module is unavailable",
            },
        )

    try:
        return {
            "available": True,
            "summary": monitoring.get_summary(window_minutes),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "available": False,
                "detail": str(exc),
            },
        )


import crm_logger

@app.get("/api/crm/clients")
async def api_crm_clients():
    clients = await run_in_threadpool(crm_logger.get_all_clients)
    return {"success": True, "clients": clients}

@app.get("/api/crm/events")
async def api_crm_events():
    events = await run_in_threadpool(crm_logger.get_recent_events, 100)
    return {"success": True, "events": events}

@app.get("/api/crm/appointments")
async def api_crm_appointments():
    appointments = await run_in_threadpool(crm_logger.get_all_appointments)
    return {"success": True, "appointments": appointments}

@app.get("/api/crm/reminders")
async def api_crm_reminders():
    reminders = await run_in_threadpool(crm_logger.get_all_reminders)
    return {"success": True, "reminders": reminders}

@app.get("/api/crm/client/{client_phone}")
async def api_crm_client_details(client_phone: str):
    prefs = await run_in_threadpool(crm_logger.get_client_preferences, client_phone)
    appointments = await run_in_threadpool(crm_logger.get_appointment_history, client_phone)
    return {"success": True, "preferences": prefs, "appointments": appointments}

@app.get("/api/crm/transcript/{session_id}")
async def api_crm_transcript(session_id: str):
    transcript = await run_in_threadpool(crm_logger.get_transcript, session_id)
    return {"success": True, "transcript": transcript}


@app.post(
    "/v1/conversation/turn",
    response_model=ConversationTurnResponse,
)
async def conversation_turn(payload: ConversationTurnRequest):
    tokens = set_request_context(
        request_id=None,
        session_id=payload.session_id,
    )

    started = time.perf_counter()

    try:
        import graph

        reply, trace_rows = await run_in_threadpool(
            graph.run_turn,
            payload.session_id,
            payload.customer_text,
            payload.caller_id,
        )

        trace = []
        for row in trace_rows or []:
            if isinstance(row, dict):
                trace.append(
                    str(
                        row.get("node_name")
                        or row.get("node")
                        or row
                    )
                )
            else:
                trace.append(str(row))

        latency_ms = round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        logger.info(
            "Conversation turn complete latency_ms=%.2f trace=%s",
            latency_ms,
            trace,
        )

        return ConversationTurnResponse(
            success=True,
            session_id=payload.session_id,
            agent_reply=reply or "",
            trace=trace,
            latency_ms=latency_ms,
        )

    finally:
        reset_request_context(tokens)


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI-compatible chat completions endpoint specifically designed for Vapi Custom LLM integration.
    """
    body = await request.json()
    model = body.get("model", "realestate-hub-agent")
    
    # 1. Identify Session ID
    # Vapi sends x-vapi-call-id header. Fallback to extracting from payload, or generate UUID.
    session_id = request.headers.get("x-vapi-call-id")
    if not session_id:
        call_obj = body.get("call")
        if isinstance(call_obj, dict):
            session_id = call_obj.get("id")
    if not session_id:
        session_id = f"vapi-{uuid.uuid4()}"

    # 2. Extract Caller Phone Number (if available)
    caller_phone = None
    call_obj = body.get("call")
    if isinstance(call_obj, dict):
        customer_obj = call_obj.get("customer")
        if isinstance(customer_obj, dict):
            caller_phone = customer_obj.get("number")
            
    if not caller_phone:
        caller_phone = os.getenv("TEST_CALLER_ID", "03000000000")
    
    # 3. Extract the latest user message
    messages = body.get("messages", [])
    customer_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            customer_text = msg.get("content") or ""
            break

    # 4. Process turn and return response
    is_stream = body.get("stream", False)
    
    if is_stream:
        async def event_generator():
            tokens = set_request_context(
                request_id=None,
                session_id=session_id,
            )
            started = time.perf_counter()
            created_time = int(time.time())
            chunk_id = f"chatcmpl-{uuid.uuid4()}"
            try:
                import graph

                # Send an initial role chunk IMMEDIATELY so Vapi doesn't
                # timeout waiting for the first byte (TTFB).
                initial_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(initial_chunk, ensure_ascii=False)}\n\n"

                # Send a filler word immediately to satisfy Vapi's CONTENT
                # timeout (Vapi ignores whitespace-only chunks).
                filler_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "Jee, "},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(filler_chunk, ensure_ascii=False)}\n\n"

                # Run graph.run_turn() in a thread while streaming periodic
                # keep-alive chunks so Vapi's content timeout never fires.
                loop = asyncio.get_event_loop()
                fut = loop.run_in_executor(None, graph.run_turn, session_id, customer_text, caller_phone)

                KEEPALIVE_INTERVAL = 2.0   # seconds between keep-alive chunks
                reply_text = ""
                graph_error = None

                while not fut.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(fut), timeout=KEEPALIVE_INTERVAL)
                    except asyncio.TimeoutError:
                        # Still processing — send a non-empty keep-alive so
                        # Vapi resets its content timeout window.
                        ka_chunk = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": "… "},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(ka_chunk, ensure_ascii=False)}\n\n"
                    except Exception:
                        break  # handled below

                try:
                    reply, _trace = await fut
                    reply_text = reply or ""
                except Exception as graph_exc:
                    logger.exception(
                        "run_turn raised an exception session_id=%s: %s",
                        session_id,
                        graph_exc,
                    )
                    reply_text = "Maafi chahta hoon, abhi ek technical masla aa gaya hai. Kya aap thodi der baad dobara try kar sakte hain?"

                latency_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "Vapi Chat Completions turn complete latency_ms=%.2f text_len=%d",
                    latency_ms,
                    len(reply_text),
                )

                # Stream the actual reply word-by-word
                words = reply_text.split(" ")
                for i, word in enumerate(words):
                    prefix = " " if i > 0 else ""
                    content_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": prefix + word},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                # Send the stop chunk
                final_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            except Exception as outer_exc:
                logger.exception(
                    "event_generator crashed session_id=%s: %s",
                    session_id,
                    outer_exc,
                )
                fallback = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "Maafi chahta hoon, ek masla aa gaya hai."},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(fallback, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            finally:
                reset_request_context(tokens)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        
    else:
        tokens = set_request_context(
            request_id=None,
            session_id=session_id,
        )
        started = time.perf_counter()
        try:
            import graph

            try:
                reply, trace_rows = await run_in_threadpool(
                    graph.run_turn,
                    session_id,
                    customer_text,
                    caller_phone,
                )
                reply_text = reply or ""
            except Exception as graph_exc:
                logger.exception(
                    "run_turn raised an exception session_id=%s: %s",
                    session_id,
                    graph_exc,
                )
                reply_text = "Maafi chahta hoon, abhi ek technical masla aa gaya hai. Kya aap thodi der baad dobara try kar sakte hain?"

            latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "Vapi Chat Completions turn complete latency_ms=%.2f text_len=%d",
                latency_ms,
                len(reply_text),
            )

            return JSONResponse(
                {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": reply_text,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": len(customer_text) // 4,
                        "completion_tokens": len(reply_text) // 4,
                        "total_tokens": (len(customer_text) + len(reply_text)) // 4,
                    },
                }
            )
        finally:
            reset_request_context(tokens)
