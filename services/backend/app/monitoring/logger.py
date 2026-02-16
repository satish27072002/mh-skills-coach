"""
Structured JSON logger with request correlation IDs.

Usage:
    from app.monitoring.logger import get_logger, log_event

    logger = get_logger(__name__)

    # Plain log
    logger.info("Something happened")

    # Structured event with context
    log_event("agent_routing", route="COACH", session_id="abc", correlation_id="xyz")
    log_event("safety_trigger", trigger_type="crisis", correlation_id="xyz")
    log_event("llm_call", model="gpt-4o-mini", duration_ms=340, correlation_id="xyz")
    log_event("error", error="OpenAI timeout", correlation_id="xyz")
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

# ---------------------------------------------------------------------------
# Context var — stores the correlation ID for the current request.
# Set at the start of each /chat request in main.py.
# ---------------------------------------------------------------------------
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def new_correlation_id() -> str:
    """Generate a new UUID4 correlation ID."""
    return str(uuid.uuid4())


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current async context."""
    _correlation_id.set(cid)


def get_correlation_id() -> str:
    """Get the current correlation ID, or generate one if not set."""
    cid = _correlation_id.get()
    if not cid:
        cid = new_correlation_id()
        _correlation_id.set(cid)
    return cid


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        # Include any extra fields attached to the record
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "id", "levelname", "levelno", "lineno", "module",
                "msecs", "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "stack_info", "thread",
                "threadName",
            ):
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        try:
            return json.dumps(payload, default=str)
        except (TypeError, ValueError):
            return json.dumps({"level": "ERROR", "message": "Failed to serialize log record"})


class TextFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    FMT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt="%H:%M:%S")


# ---------------------------------------------------------------------------
# Root logger setup — call once at startup
# ---------------------------------------------------------------------------
_configured = False


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure the root logger. Call once during app startup."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Uses the root configuration."""
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Structured event logging helper
# ---------------------------------------------------------------------------
_event_logger = logging.getLogger("mh.events")


def log_event(event: str, **kwargs: Any) -> None:
    """Log a structured event with arbitrary key-value context.

    Args:
        event: event name, e.g. "agent_routing", "llm_call", "safety_trigger"
        **kwargs: any additional fields to include in the log record
    """
    extra = {"event": event, "correlation_id": get_correlation_id(), **kwargs}
    _event_logger.info(event, extra=extra)


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------
class Timer:
    """Simple context manager to measure elapsed time in milliseconds."""

    def __init__(self) -> None:
        self._start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
