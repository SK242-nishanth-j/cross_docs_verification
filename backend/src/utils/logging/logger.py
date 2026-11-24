"""
File: logger.py
Purpose: Structured JSON logger with correlation-ID support.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import logging
from contextvars import ContextVar
from typing import Any

from src.config.settings import get_settings
from src.utils.logging.formatters import JSONFormatter

# Holds the correlation ID of the request being handled.
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class GenAILogger:
    """Emit JSON log lines that carry the current correlation ID.

    Never pass credentials, personal data or document contents as fields.
    """

    def __init__(self, name: str, service_name: str, level: str) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(JSONFormatter(service_name))
            self._logger.addHandler(handler)
            self._logger.setLevel(level)
            self._logger.propagate = False

    # ``message`` is positional-only so a field may also be called "message".
    def debug(self, message: str, /, **fields: Any) -> None:
        """Log at DEBUG level."""
        self._log(logging.DEBUG, message, fields)

    def info(self, message: str, /, **fields: Any) -> None:
        """Log at INFO level."""
        self._log(logging.INFO, message, fields)

    def warning(self, message: str, /, **fields: Any) -> None:
        """Log at WARNING level."""
        self._log(logging.WARNING, message, fields)

    def error(self, message: str, /, **fields: Any) -> None:
        """Log at ERROR level."""
        self._log(logging.ERROR, message, fields)

    def _log(self, level: int, message: str, fields: dict[str, Any]) -> None:
        self._logger.log(
            level,
            message,
            extra={"fields": fields, "correlation_id": correlation_id.get()},
        )


def get_logger(name: str) -> GenAILogger:
    """Return a logger configured from the application settings.

    Args:
        name: Logger name, normally ``__name__``.

    Returns:
        A ``GenAILogger`` bound to ``name``.
    """
    settings = get_settings()
    return GenAILogger(name, settings.service_name, settings.log_level)
