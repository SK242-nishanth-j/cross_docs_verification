from __future__ import annotations

import datetime as dt

import pytest
from conftest import codes


@pytest.mark.parametrize(
    "candidate",
    [
        "12/03/1998",
        "12.03.1998",
        "1998-03-12",
        "12 Mar 1998",
        "12-Mar-1998",
        "12th March, 1998",
        "DOB: 12/03/1998",
        "Date of Birth - 12-03-1998",
        "\u0967\u0968-\u0966\u0969-\u0967\u096f\u096f\u096e",  # Devanagari digits
        dt.date(1998, 3, 12),
        dt.datetime(1998, 3, 12, 10, 30),
    ],
)
def test_same_date_in_any_format_is_green(compare, candidate):  # type: ignore[no-untyped-def]
    result = compare("dob", "12-03-1998", candidate)
    assert result["color"] == "green", codes(result)


def test_day_and_month_swapped_is_red(compare):  # type: ignore[no-untyped-def]
    result = compare("dob", "12-03-1998", "03/12/1998")
    assert (result["color"], codes(result)) == ("red", ["DATE_DIFFERENT"])
    assert {c["component"]: c["relation"] for c in result["components"]} == {
        "day": "conflict",
        "month": "conflict",
        "year": "match",
    }


@pytest.mark.parametrize("candidate", ["12-03-98", "1998", "03-1998", "March 1998", "YOB: 1998", 1998, 1998.0])
def test_a_date_without_day_month_and_four_digit_year_is_red(compare, candidate):  # type: ignore[no-untyped-def]
    result = compare("dob", "12-03-1998", candidate)
    assert (result["color"], codes(result)) == ("red", ["UNPARSEABLE"])


def test_a_date_is_never_yellow(compare):  # type: ignore[no-untyped-def]
    for candidate in ("12-03-1998", "12-03-1999", "13-03-1998", "21-03-1998", "03/12/1998", "12-03-98", "1998"):
        assert compare("dob", "12-03-1998", candidate)["color"] in ("green", "red"), candidate


def test_different_dates_are_red_and_the_differing_part_is_marked(compare):  # type: ignore[no-untyped-def]
    result = compare("dob", "12-03-1998", "12-03-1999")
    assert result["color"] == "red"
    assert {seg["text"]: seg["kind"] for seg in result["highlight"]["candidate"]}["1999"] == "conflict"


def test_one_digit_difference_is_red_with_a_typo_hint(compare):  # type: ignore[no-untyped-def]
    near = compare("dob", "12-03-1998", "21-03-1998")  # one digit off
    assert (near["color"], "POSSIBLE_TYPO" in codes(near)) == ("red", True)
    far = compare("dob", "12-03-1998", "25-07-1985")  # nothing equal
    assert (far["color"], "POSSIBLE_TYPO" in codes(far)) == ("red", False)


@pytest.mark.parametrize(
    ("candidate", "code"),
    [
        ("31-02-1998", "UNPARSEABLE"),
        ("12-03-2030", "DATE_IMPLAUSIBLE"),
        ("12-03-1800", "DATE_IMPLAUSIBLE"),
        ("hello", "UNPARSEABLE"),
        ("99-99-9999", "UNPARSEABLE"),
        ("", "MISSING_VALUE"),
        ("N/A", "MISSING_VALUE"),
        (True, "UNPARSEABLE"),
        (["12-03-1998"], "UNPARSEABLE"),
        ("1" * 100, "TOO_LONG"),
    ],
)
def test_unreadable_dates_are_red(compare, candidate, code):  # type: ignore[no-untyped-def]
    result = compare("dob", "12-03-1998", candidate)
    assert (result["color"], codes(result)) == ("red", [code])
