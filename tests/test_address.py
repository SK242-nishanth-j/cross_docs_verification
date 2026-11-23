from __future__ import annotations

import pytest
from conftest import codes

import cross_verify as cv

BASE = "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore - 560034"


@pytest.fixture(scope="module")
def cfg():  # type: ignore[no-untyped-def]
    return cv.load_config()


def test_parse_splits_an_address_into_parts(cfg):  # type: ignore[no-untyped-def]
    parsed = cv.parse_address(BASE, cfg, "base")
    assert (parsed["pincode"], parsed["city"]) == ("560034", "bengaluru")
    assert sorted(n["value"] for n in parsed["numbers"]) == ["402", "cross:2"]
    assert [w["norm"] for w in parsed["words"]] == ["sai", "residency", "koramangala"]


def test_parse_handles_house_number_formats_and_state_names(cfg):  # type: ignore[no-untyped-def]
    parsed = cv.parse_address("H.No. 12-3/4, Sector 5, Indira Nagar, Pune, Maharashtra 411 001", cfg, "base")
    assert (parsed["pincode"], parsed["city"]) == ("411001", "pune")
    assert sorted(n["value"] for n in parsed["numbers"]) == ["12/3/4", "sector:5"]
    assert [w["norm"] for w in parsed["words"]] == ["indira"]  # 'maharashtra' and 'nagar' say nothing


def test_same_address_written_differently_is_green(compare):  # type: ignore[no-untyped-def]
    for candidate in [
        "S/O Ramesh, 402 Sai Residency, 2nd Cross, Koramangala, Bengaluru, Karnataka 560034",
        "FLAT NO. 402, SAI RESIDENCY, SECOND CROSS, KORAMANGALA, BENGALURU KA 560034",
        "Address: 402 Sai Residency 2nd Cross Koramangala Bangalore 560034",
        "402, Sai Residency, 2 Cross, Koramangala, Bangalore, 560 034",
    ]:
        result = compare("address", BASE, candidate)
        assert result["color"] == "green", (candidate, codes(result))


def test_spelling_difference_is_yellow_and_highlighted(compare):  # type: ignore[no-untyped-def]
    result = compare("address", BASE, "402, Sai Residence, 2 Cross, Koramangala, Bengaluru 560034")
    assert (result["color"], codes(result)) == ("yellow", ["SPELLING_VARIANT"])
    kinds = {seg["text"]: seg["kind"] for seg in result["highlight"]["candidate"]}
    assert (kinds["Residence"], kinds["560034"]) == ("spelling", "match")
    assert {c["component"]: c["status"] for c in result["components"]}["text"] == "spelling"
    assert result["normalized"] == "cross:2 402, sai residence koramangala, bengaluru, 560034"


def test_plural_words_are_the_same_word(compare):  # type: ignore[no-untyped-def]
    assert (
        compare("address", "12 MG Road Sai Apartments Pune 411001", "12 MG Road Sai Apartment Pune 411001")["color"]
        == "green"
    )


def test_different_house_and_pincode_is_red_and_marked(compare):  # type: ignore[no-untyped-def]
    candidate = "12, 5th Main, Indiranagar, Bengaluru 560038"
    result = compare("address", BASE, candidate)
    assert result["color"] == "red"
    assert {"PINCODE_MISMATCH", "NUMBER_MISMATCH"} <= set(codes(result))
    kinds = {seg["text"]: seg["kind"] for seg in result["highlight"]["candidate"]}
    assert (kinds["560038"], kinds["12"]) == ("conflict", "conflict")
    assert "".join(seg["text"] for seg in result["highlight"]["candidate"]) == candidate


def test_a_vague_address_without_pincode_or_house_number_is_red(compare):  # type: ignore[no-untyped-def]
    assert "NO_ANCHOR_MATCH" in codes(compare("address", BASE, "Koramangala, Bengaluru"))


def test_pincode_one_digit_off_is_yellow_only_when_nothing_else_disagrees(compare):  # type: ignore[no-untyped-def]
    near = compare("address", BASE, "402, Sai Residency, 2nd Cross, Koramangala, Bengaluru 560035")
    assert (near["color"], codes(near)) == ("yellow", ["PINCODE_NEAR"])
    assert compare("address", BASE, "402, Sai Residency, 2nd Cross, Koramangala, Bengaluru 600001")["color"] == "red"
    assert "PINCODE_MISMATCH" in codes(
        compare("address", BASE, "12, Sai Residency, 2nd Cross, Koramangala, Bengaluru 560035")
    )


def test_different_city_is_red(compare):  # type: ignore[no-untyped-def]
    result = compare("address", BASE, "402, Sai Residency, 2nd Cross, Koramangala, Chennai 600001")
    assert {"CITY_MISMATCH", "PINCODE_MISMATCH"} <= set(codes(result))


def test_house_and_street_numbers(compare):  # type: ignore[no-untyped-def]
    assert "NUMBER_SUBSET" in codes(
        compare("address", BASE, "402/1, Sai Residency, 2nd Cross, Koramangala, Bengaluru 560034")
    )
    assert "NUMBER_MISMATCH" in codes(
        compare("address", BASE, "420, Sai Residency, 2nd Cross, Koramangala, Bengaluru 560034")
    )
    assert "NUMBER_MISMATCH" in codes(
        compare("address", BASE, "402, Sai Residency, 5th Cross, Koramangala, Bengaluru 560034")
    )


def test_parts_missing_on_one_side_are_yellow(compare):  # type: ignore[no-untyped-def]
    for candidate in (
        "Sai Residency, Koramangala, Bengaluru 560034",
        "402 Sai Residency 2nd Cross Koramangala Bengaluru",
    ):
        result = compare("address", BASE, candidate)
        assert (result["color"], codes(result)) == ("yellow", ["INCOMPLETE_ADDRESS"])


def test_a_different_locality_with_the_same_anchors_is_yellow(compare):  # type: ignore[no-untyped-def]
    result = compare("address", BASE, "402, Sai Residency, 2nd Cross, Ejipura, Bengaluru 560034")
    assert (result["color"], codes(result)) == ("yellow", ["WORDS_PARTIAL"])


def test_unreadable_addresses_are_red(compare):  # type: ignore[no-untyped-def]
    assert codes(compare("address", BASE, "")) == ["MISSING_VALUE"]
    assert codes(compare("address", BASE, "!!! ???")) == ["UNPARSEABLE"]
    assert codes(compare("address", BASE, "\u0928\u0908 \u0926\u093f\u0932\u094d\u0932\u0940")) == [
        "UNSUPPORTED_SCRIPT"
    ]
    assert codes(compare("address", BASE, "x" * 1200)) == ["TOO_LONG"]
