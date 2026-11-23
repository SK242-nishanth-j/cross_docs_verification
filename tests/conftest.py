"""Shared test helpers. Tests use the real configuration file and a fixed date."""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so the tests find cross_verify.py

import cross_verify as cv  # noqa: E402

TODAY = dt.date(2026, 11, 13)

Comparison = dict[str, Any]


@pytest.fixture(scope="session")
def verify() -> Callable[..., dict[str, Any]]:
    verifier: Callable[..., dict[str, Any]] = cv.create_verifier()
    return verifier


@pytest.fixture(scope="session")
def compare(verify: Callable[..., dict[str, Any]]) -> Callable[..., Comparison]:
    """compare("name", base, candidate) -> the single comparison result."""

    def _compare(field_type: str, base: Any, candidate: Any, **extra: Any) -> Comparison:
        check = {
            "field": field_type,
            "type": field_type,
            "base": base,
            "candidates": [{"source": "doc", "value": candidate, **extra}],
        }
        report = verify([check], today=TODAY)
        comparison: Comparison = report["fields"][0]["comparisons"][0]
        return comparison

    return _compare


def codes(result: Comparison) -> list[str]:
    return [reason["code"] for reason in result["reasons"]]
