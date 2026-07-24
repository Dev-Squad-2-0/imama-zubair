"""
Structured logging so logs are easy to ship to a monitoring system later
(each line is one JSON object -> trivial to parse in Datadog/CloudWatch/etc).
"""
import json
import logging
import os
import sys
import time

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # allow extra structured fields via logger.info("msg", extra={"event": {...}})
        if hasattr(record, "event"):
            payload["event"] = record.event
        return json.dumps(payload)


def get_logger(name: str = "onboarding_agent") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid duplicate handlers on reload
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "agent.log"))
    file_handler.setFormatter(JsonFormatter())

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JsonFormatter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def log_event(logger: logging.Logger, event_type: str, **fields):
    """Convenience helper: log_event(logger, 'tool_call', tool='calculator', latency_ms=12)"""
    logger.info(event_type, extra={"event": {"type": event_type, **fields}})
