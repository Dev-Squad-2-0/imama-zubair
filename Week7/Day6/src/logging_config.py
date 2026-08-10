"""Structured application logging for deployment.

- JSON logs by default for Docker/CI/production.
- Plain text can be enabled with LOG_FORMAT=text.
- Request/session IDs can be attached through context variables.
- Common secret-looking values are redacted from log messages.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


_request_id_var = contextvars.ContextVar("request_id", default=None)
_session_id_var = contextvars.ContextVar("session_id", default=None)

_CONFIGURED = False

_SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_ -]?key|token|secret|password|authorization)"
        r"\b\s*[:=]\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-=]+"),
]


def set_request_context(
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    request_token = _request_id_var.set(request_id)
    session_token = _session_id_var.set(session_id)
    return request_token, session_token


def reset_request_context(tokens) -> None:
    if not tokens:
        return
    request_token, session_token = tokens
    _request_id_var.reset(request_token)
    _session_id_var.reset(session_token)


def _redact(value: Any) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        if "bearer" in pattern.pattern.lower():
            text = pattern.sub("Bearer [REDACTED]", text)
        else:
            text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }

        request_id = _request_id_var.get()
        session_id = _session_id_var.get()

        if request_id:
            payload["request_id"] = request_id
        if session_id:
            payload["session_id"] = session_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class ContextTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = _request_id_var.get() or "-"
        session_id = _session_id_var.get() or "-"
        message = _redact(record.getMessage())

        base = (
            f"%(asctime)s %(levelname)s %(name)s "
            f"request_id={request_id} session_id={session_id} "
        )
        formatter = logging.Formatter(base + "%(message)s")
        record.msg = message
        record.args = ()
        return formatter.format(record)


def configure_logging(force: bool = False) -> None:
    global _CONFIGURED

    if _CONFIGURED and not force:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    root = logging.getLogger()
    root.setLevel(level)

    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if log_format == "text":
            handler.setFormatter(ContextTextFormatter())
        else:
            handler.setFormatter(JsonFormatter())
        root.addHandler(handler)

    # Keep noisy libraries readable in container logs.
    for noisy_logger in (
        "httpcore",
        "httpx",
        "urllib3",
        "multipart",
    ):
        logging.getLogger(noisy_logger).setLevel(
            os.getenv("DEPENDENCY_LOG_LEVEL", "WARNING").upper()
        )

    _CONFIGURED = True
