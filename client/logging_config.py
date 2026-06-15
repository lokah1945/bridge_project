"""Structured logging configuration with secrets redaction."""
import logging
import re
from typing import Any

from client.config import settings


# Patterns that likely indicate sensitive values.
_SENSITIVE_PATTERNS = [
    re.compile(r"(Authorization\s*[:=]\s*Bearer\s+)[\w\-\.]+", re.IGNORECASE),
    re.compile(r"(ENCRYPTION_KEY\s*[:=]\s*)[\w\-/=]+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[\w\-]+", re.IGNORECASE),
    re.compile(r"(cookie\s*[:=]\s*)[^\s,;]+", re.IGNORECASE),
    re.compile(r"(session\s*[:=]\s*)[^\s,;]+", re.IGNORECASE),
]


class SecretsRedactingFilter(logging.Filter):
    """Redact sensitive values from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in _SENSITIVE_PATTERNS:
                record.msg = pattern.sub(r"\1<REDACTED>", record.msg)
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern in _SENSITIVE_PATTERNS:
                        arg = pattern.sub(r"\1<REDACTED>", arg)
                new_args.append(arg)
            record.args = tuple(new_args)
        return True


def setup_logging() -> logging.Logger:
    """Configure root logger for the bridge-client."""
    logger = logging.getLogger("bridge_client")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
            )
        )
        handler.addFilter(SecretsRedactingFilter())
        logger.addHandler(handler)

    return logger


logger = setup_logging()
