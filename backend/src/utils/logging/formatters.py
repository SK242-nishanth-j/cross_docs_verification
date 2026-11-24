"""
File: formatters.py
Purpose: JSON log formatter with a consistent set of fields.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import json
import logging
from datetime import UTC
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Render each log record as a single JSON object."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a log record.

        Args:
            record: The record emitted by the logger.

        Returns:
            One JSON line. Extra fields never override the base fields.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "service": self._service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                entry.setdefault(str(key), value)
        return json.dumps(entry, default=str)
