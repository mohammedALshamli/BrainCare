"""Structured logging helpers.

The application emits one JSON object per log record in production. A request
identifier is attached through a context variable so that log lines produced
while handling a request can be correlated without passing the request around.
"""

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_RESERVED_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "request_id"}

_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|api[_-]?key|"
    r"refresh|credential)"
)
_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)((?:password|passwd|secret|token|api[_-]?key|refresh|"
        r"credential)\s*[:=]\s*)[^\s,;}\]]+"
    ),
)


def redact_text(value: str) -> str:
    for pattern in _SENSITIVE_PATTERNS:
        value = pattern.sub(r"\1[REDACTED]", value)
    return value


class SensitiveDataFilter(logging.Filter):
    """Redact common credentials before a record reaches any formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        redact_all_args = isinstance(record.msg, str) and bool(
            _SENSITIVE_KEY.search(record.msg)
        )
        if isinstance(record.msg, str) and not record.args:
            record.msg = redact_text(record.msg)

        if isinstance(record.args, dict):
            record.args = {
                key: "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else redact_text(value)
                if isinstance(value, str)
                else value
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(
                "[REDACTED]"
                if redact_all_args and isinstance(value, str)
                else redact_text(value)
                if isinstance(value, str)
                else value
                for value in record.args
            )

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_LOG_RECORD_ATTRS or key.startswith("_"):
                continue
            if _SENSITIVE_KEY.search(key):
                record.__dict__[key] = "[REDACTED]"
            elif isinstance(value, str):
                record.__dict__[key] = redact_text(value)
        return True


def normalise_request_id(value: str | None) -> str | None:
    """Return a safe request id or ``None`` when the supplied value is unusable."""
    if value and _VALID_REQUEST_ID.match(value):
        return value
    return None


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
            "request_id": getattr(record, "request_id", "-"),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str)
