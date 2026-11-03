"""Structured logging with redaction of secret-looking fields (CG-5)."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(secret|token|password|passwd|api_?key|api_?hash|session|credential|authorization|private)",
    re.IGNORECASE,
)
REDACTED = "***"

# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact(value: Any, key: str | None = None) -> Any:
    """Mask values under secret-looking keys, recursing into dicts and lists."""
    if key is not None and SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, message, extra fields, optional exc."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = redact(value, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _PlainFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")


def configure_logging(level: str = "INFO", json_output: bool = True, stream=None) -> None:
    """Install one stream handler on the root logger. Safe to call repeatedly."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_sie_handler", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if json_output else _PlainFormatter())
    handler._sie_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Third-party migration chatter stays quiet unless we are debugging.
    logging.getLogger("alembic").setLevel(
        logging.DEBUG if root.level == logging.DEBUG else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
