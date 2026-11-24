"""
File: case_store.py
Purpose: JSON file store, one folder per case: <data_dir>/<case_id>/{lead.json, result.json, runs/}.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

OCR text is stored only after Aadhaar masking; the raw OCR JSON is never stored.
"""

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.services.models import CASE_ID_PATTERN

_CASE_ID = re.compile(CASE_ID_PATTERN)


class CaseStore:
    """Atomic JSON writes per case; one lock per case serialises runs."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, case_id: str) -> threading.Lock:
        """Return the lock of one case.

        Args:
            case_id: The case.

        Returns:
            A lock shared by every caller of this case.
        """
        with self._guard:
            return self._locks.setdefault(case_id, threading.Lock())

    def _dir(self, case_id: str) -> Path:
        """Return the folder of a case, refusing IDs that would leave the data folder."""
        if not _CASE_ID.fullmatch(case_id):
            raise ValueError("invalid case_id")
        path = (self._root / case_id).resolve()
        if path.parent != self._root:
            raise ValueError("invalid case_id")
        return path

    @staticmethod
    def _write(path: Path, data: Any) -> None:
        """Write JSON atomically (temporary file, then rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _read(path: Path) -> Any:
        """Read JSON, or None when the file does not exist."""
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_lead(self, case_id: str, record: dict[str, Any]) -> None:
        """Store the lead of a case.

        Args:
            case_id: The case.
            record: The lead record.
        """
        self._write(self._dir(case_id) / "lead.json", record)

    def get_lead(self, case_id: str) -> dict[str, Any] | None:
        """Return the stored lead record.

        Args:
            case_id: The case.

        Returns:
            The lead record, or None.
        """
        record: dict[str, Any] | None = self._read(self._dir(case_id) / "lead.json")
        return record

    def save_run(self, case_id: str, run_id: str, record: dict[str, Any]) -> None:
        """Store one run record (input summary, status, result).

        Args:
            case_id: The case.
            run_id: The run.
            record: The run record.
        """
        self._write(self._dir(case_id) / "runs" / f"{run_id}.json", record)

    def save_result(self, case_id: str, record: dict[str, Any]) -> None:
        """Store the latest result of a case.

        Args:
            case_id: The case.
            record: The run result.
        """
        self._write(self._dir(case_id) / "result.json", record)

    def get_result(self, case_id: str) -> dict[str, Any] | None:
        """Return the latest result of a case.

        Args:
            case_id: The case.

        Returns:
            The run result, or None.
        """
        record: dict[str, Any] | None = self._read(self._dir(case_id) / "result.json")
        return record
