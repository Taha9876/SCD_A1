"""Structured JSON logging to stdout.

stdout, never a file: a container filesystem is ephemeral and the log shipper
(and `kubectl logs`, and `docker compose logs`) reads the stream. A file inside
the image is a log nobody will ever see again after a restart.

Every line carries the request_id from the contextvar, so a single citizen
submission can be followed from the route, through triage, to the fallback
warning, without correlating on timestamps.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

#: Keys the logging module puts on every record. Everything else on a record
#: is application context and gets serialised into the JSON line.
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}

#: Defence in depth. Nothing should ever pass a credential to a logger, but if
#: something does, it must not become a permanent record in a log aggregator.
_SECRET_HINTS = ("api_key", "apikey", "authorization", "password", "secret", "token")


def _scrub(key: str, value: object) -> object:
    if any(hint in key.lower() for hint in _SECRET_HINTS):
        return "***redacted***"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _scrub(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn ships its own handlers; route them through ours so the whole
    # stream is one JSON format rather than two interleaved ones.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
