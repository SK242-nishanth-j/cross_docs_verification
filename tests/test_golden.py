"""Every row of golden_cases.csv must give the expected colour.

The CSV is the sign-off table: change a row only when the business rule changes.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

GOLDEN = Path(__file__).with_name("golden_cases.csv")


def _rows() -> list[tuple[str, str, str, str]]:
    with GOLDEN.open("r", encoding="utf-8", newline="") as handle:
        return [(r["type"], r["base"], r["candidate"], r["expected"]) for r in csv.DictReader(handle)]


@pytest.mark.parametrize(("field_type", "base", "candidate", "expected"), _rows())
def test_golden_case(compare, field_type, base, candidate, expected):  # type: ignore[no-untyped-def]
    result = compare(field_type, base, candidate)
    reasons = [r["code"] for r in result["reasons"]]
    assert result["color"] == expected, f"{base!r} vs {candidate!r}: {result['color']} {reasons}"
