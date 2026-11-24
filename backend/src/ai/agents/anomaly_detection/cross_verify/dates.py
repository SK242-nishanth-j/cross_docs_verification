"""
File: dates.py
Purpose: Parse and compare dates of birth.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: rapidfuzz
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from rapidfuzz.distance import OSA

from .constants import Json
from .constants import Span
from .text import add_reason
from .text import ascii_digits
from .text import failure
from .text import make_outcome

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
# A date of birth is day, month, year in that order (month as a number or a name, four-digit year).
# Green only when day, month and year are all equal. Any other date is red. A year-first date (1998-03-12) is also read.
_SEP = r"[\s\-/.,]*"
_NUMERIC = re.compile(
    r"(?<!\d)(\d{1,4})\s*([/\-.])\s*(\d{1,2})\s*\2\s*(\d{1,4})(?!\d)"
)  # 12-03-1998
_DAY_MONTH_NAME = re.compile(
    rf"(?<![a-z\d])(\d{{1,2}})(?:st|nd|rd|th)?{_SEP}([a-z]{{3,9}})\.?{_SEP}(\d{{4}})(?!\d)"
)
_PARTS = ("day", "month", "year")


def _span(m: re.Match[str], group: int, offset: int) -> tuple[int, int]:
    return m.start(group) + offset, m.end(group) + offset


def _build(
    year: int,
    month: int,
    day: int,
    spans: dict[str, tuple[int, int]],
    today: dt.date,
    max_age: int,
) -> Json:
    """One date. An error if it does not exist (UNPARSEABLE) or is in the future or too old (DATE_IMPLAUSIBLE)."""
    try:
        when = dt.date(year, month, day)
    except ValueError:
        return {"error": "UNPARSEABLE"}
    if when > today or year < today.year - max_age:
        return {"error": "DATE_IMPLAUSIBLE"}
    return {"year": year, "month": month, "day": day, "spans": spans}


def _numeric_date(text: str, offset: int, today: dt.date, max_age: int) -> Json | None:
    """12-03-1998, 12/03/1998, 12.03.1998 (day, month, year), or year first: 1998-03-12."""
    m = _NUMERIC.search(text)
    if not m:
        return None
    first, last = len(m.group(1)), len(m.group(4))
    if first <= 2 and last == 4:  # day, month, year
        groups = {"day": 1, "month": 3, "year": 4}
    elif first == 4 and last <= 2:  # year, month, day
        groups = {"year": 1, "month": 3, "day": 4}
    else:  # for example a two-digit year
        return None
    value = {part: int(m.group(group)) for part, group in groups.items()}
    spans = {part: _span(m, group, offset) for part, group in groups.items()}
    return _build(value["year"], value["month"], value["day"], spans, today, max_age)


def _named_month_date(
    text: str, offset: int, today: dt.date, max_age: int
) -> Json | None:
    """12 March 1998, 12th March, 1998, 12-Mar-1998 (day, month name, year)."""
    for m in _DAY_MONTH_NAME.finditer(text):
        if m.group(2) in _MONTHS:
            spans = {
                "day": _span(m, 1, offset),
                "month": _span(m, 2, offset),
                "year": _span(m, 3, offset),
            }
            return _build(
                int(m.group(3)),
                _MONTHS[m.group(2)],
                int(m.group(1)),
                spans,
                today,
                max_age,
            )
    return None


def _read_date(text: str, offset: int, today: dt.date, max_age: int) -> Json | None:
    """Try each date format in turn. None when the text holds no full date."""
    for reader in (_numeric_date, _named_month_date):
        found: Json | None = reader(text, offset, today, max_age)
        if found:
            return found
    return None


def _iso(found: Json) -> str:
    return f"{found['year']:04d}-{found['month']:02d}-{found['day']:02d}"


def parse_dob(value: Any, text: str, cfg: Json, side: str, today: dt.date) -> Json:
    """Read a date of birth. It needs a day, a month and a four-digit year.

    Args:
        value: The original value (a date object is used as is).
        text: The value as text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.
        today: Reference date; later dates and very old ones are implausible.

    Returns:
        The parsed date ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    reasons: list[Json] = []
    ignored: list[Span] = []
    max_age = cfg["dob"]["max_age"]
    found: Json | None
    if isinstance(value, dt.date):  # a real date object: nothing to read
        day = value.date() if isinstance(value, dt.datetime) else value
        found = _build(day.year, day.month, day.day, {}, today, max_age)
    else:
        lowered = "".join(
            low if len(low := ch.lower()) == 1 else ch for ch in ascii_digits(text)
        )
        start = 0
        label = cfg["_rt"]["dob_label"].search(lowered)
        if label:
            start = label.end()
            ignored.append((label.start(), label.end(), "ignored"))
            add_reason(
                reasons,
                cfg,
                "LABEL_STRIPPED",
                f"A label was removed from the {side} date.",
            )
        found = _read_date(lowered[start:], start, today, max_age)
    if found is None:
        return failure(
            "UNPARSEABLE",
            f"No full date (day, month and year) could be read from the {side} value.",
        )
    if "error" in found:
        message = (
            "is in the future or too far in the past"
            if found["error"] == "DATE_IMPLAUSIBLE"
            else "is not a real date"
        )
        return failure(found["error"], f"The {side} date {message}.")
    return {
        "ok": True,
        "raw": text,
        **found,  # year, month, day, spans
        "ignored": ignored,
        "reasons": reasons,
        "normalized": _iso(found),
    }


def _digits(found: Json) -> str:
    return f"{found['year']:04d}{found['month']:02d}{found['day']:02d}"


def compare_dobs(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two parsed dates part by part (day, month, year).

    Green only when all three are equal.

    Args:
        base: Parsed base date.
        cand: Parsed candidate date.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons, highlight spans and a day/month/year table.
    """
    reasons = [*base["reasons"], *cand["reasons"]]
    equal = {part: base[part] == cand[part] for part in _PARTS}
    same = all(equal.values())
    if same:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The dates are the same.")
    else:
        differing = [p for p in _PARTS if not equal[p]]
        near = (
            OSA.distance(_digits(base), _digits(cand)) == 1
        )  # one digit off: maybe a typing error
        add_reason(
            reasons, cfg, "DATE_DIFFERENT", f"The {', '.join(differing)} differ."
        )
        if near:
            add_reason(
                reasons,
                cfg,
                "POSSIBLE_TYPO",
                "The dates differ by a single digit, which may be a typing error.",
            )

    out = make_outcome(reasons, same, base, cand)
    out["components"] = []
    for part in _PARTS:
        kind = "match" if equal[part] else "conflict"
        if part in base["spans"]:
            out["base_spans"].append((*base["spans"][part], kind))
        if part in cand["spans"]:
            out["cand_spans"].append((*cand["spans"][part], kind))
        out["components"].append(
            {
                "component": part,
                "base": base[part],
                "candidate": cand[part],
                "relation": kind,
            }
        )
    return out
