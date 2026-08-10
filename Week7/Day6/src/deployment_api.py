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

import logging
import os
import sqlite3
import sys
import threading
import time
import uuid
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
from fastapi.responses import JSONResponse
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


def _warm_rag_background() -> None:
    if not _env_true("RAG_WARMUP_ON_API_START", "1"):
        logger.info("RAG background warmup disabled")
        return

    def worker():
        try:
            import rag_pipeline

            warmup = getattr(rag_pipeline, "warmup", None)
            if callable(warmup):
                result = warmup()
                logger.info("RAG background warmup result: %s", result)
            else:
                # Older project version: connect collection as a light fallback.
                rag_pipeline.get_collection()
                logger.info("RAG collection connected during startup warmup")
        except Exception as exc:
            # Startup must not fail solely because RAG warmup failed.
            logger.warning("RAG background warmup failed: %s", exc)

    threading.Thread(
        target=worker,
        name="api-rag-warmup",
        daemon=True,
    ).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting RealEstate Hub API env=%s",
        os.getenv("APP_ENV", "development"),
    )
    _warm_rag_background()
    yield
    logger.info("Stopping RealEstate Hub API")


app = FastAPI(
    title="RealEstate Hub Voice Agent API",
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
)


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
