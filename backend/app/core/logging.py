"""Structured JSON logging with secret redaction.

Two properties matter here:

1. Logs are machine-readable, because the audit trail (DPRD F13) and the demo-day debugging
   loop both depend on being able to grep a trace by ``request_id``.
2. No API key ever reaches a log line. ``RedactingFilter`` scrubs configured secret values
   and common key-bearing query parameters from every record before it is emitted.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

# Query params that carry credentials across the providers we use.
_KEY_PARAM_RE = re.compile(
    r"((?:api[-_]?key|apikey|access[-_]?token|auth|secret)=)[^&\s\"']+",
    re.IGNORECASE,
)


class RedactingFilter(logging.Filter):
    """Removes known secret values and key-bearing query params from log records."""

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        # Only redact non-trivial values; a 1-char "secret" would mangle every line.
        self._secrets = tuple(s for s in secrets if len(s) >= 8)

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***REDACTED***")
        return _KEY_PARAM_RE.sub(r"\1***REDACTED***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            record.args = tuple(
                self._scrub(a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED and isinstance(value, str):
                record.__dict__[key] = self._scrub(value)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with request correlation and extra fields inlined."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", secrets: tuple[str, ...] = ()) -> None:
    """Install the JSON formatter and redaction filter on the root logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter(secrets))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers; route them through ours so redaction applies.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
