from __future__ import annotations

from conftest import codes


def test_same_name_after_cleanup_is_green(compare):  # type: ignore[no-untyped-def]
    for base, candidate in [
        ("Nishanth", "Mr. NISHANTH"),
        ("Nishanth", "Name: Nishanth S/O Ramesh"),
        ("O'Brien", "OBrien"),
        ("José", "JOSE"),
        ("Nishanth J S", "NISHANTH JS"),
        ("Kumari Devi", "Kumari Devi"),
        ("Sri Ram Kumar", "Sri Ram Kumar"),
    ]:
        result = compare("name", base, candidate)
        assert (result["color"], result["needs_review"]) == ("green", False), (base, candidate)


def test_swapped_words_are_yellow(compare):  # type: ignore[no-untyped-def]
    result = compare("name", "kumar sam", "sam kumar")
    assert (result["color"], codes(result)) == ("yellow", ["TOKEN_ORDER_DIFFERENT"])


def test_a_replaced_word_is_red(compare):  # type: ignore[no-untyped-def]
    result = compare("name", "kumar sam", "sam ramu")
    assert (result["color"], codes(result)) == ("red", ["TOKEN_CONFLICT"])


def test_initials(compare):  # type: ignore[no-untyped-def]
    extra = compare("name", "Nishanth", "Nishanth J S")
    assert (extra["color"], codes(extra)) == ("yellow", ["EXTRA_INITIALS"])
    assert "INITIAL_EXPANDED" in codes(compare("name", "Nishanth Jayakumar", "Nishanth J"))
    assert compare("name", "Nishanth Jayakumar S", "N J S")["color"] == "yellow"  # initials only
    assert compare("name", "S. Nishanth", "Nishanth S")["color"] == "yellow"
    assert "INSUFFICIENT_NAME" in codes(compare("name", "Nishanth", "N"))  # one letter is not enough


def test_missing_or_extra_words_are_always_yellow(compare):  # type: ignore[no-untyped-def]
    """The colour comes from the reasons only: however many words are missing or extra, it stays yellow."""
    assert codes(compare("name", "Sam", "Sam Kumar")) == ["EXTRA_TOKEN"]
    assert codes(compare("name", "Sam Kumar", "Sam")) == ["MISSING_TOKEN"]
    result = compare("name", "Anand Bhaskar Chandra Dinesh Eswar", "Anand")
    assert (result["color"], codes(result)) == ("yellow", ["MISSING_TOKEN"])


def test_one_word_written_as_two_is_yellow(compare):  # type: ignore[no-untyped-def]
    assert codes(compare("name", "Nishanth Kumar", "Nishanthkumar")) == ["SPACING_DIFFERENCE"]


def test_a_different_spelling_is_red(compare):  # type: ignore[no-untyped-def]
    """Names are compared letter for letter. There are no spelling lists and no spelling tolerance."""
    pairs = [("Vinay", "Vijay"), ("Nishanth", "Nishant"), ("Ramesh", "Rakesh"), ("Arun", "Varun"), ("Kumar", "Kumari")]
    pairs += [("Sam", "Ram"), ("Mohd", "Mohammed"), ("Laxmi", "Lakshmi"), ("Venkat", "Venkata")]
    for base, candidate in pairs:
        result = compare("name", base, candidate)
        assert (result["color"], codes(result)) == ("red", ["TOKEN_CONFLICT"]), (base, candidate)
    assert compare("name", "Vinay", "Vinay")["color"] == "green"
    assert compare("name", "Vinay", "VINAY.")["color"] == "green"


def test_digits_inside_a_word_are_ocr_noise(compare):  # type: ignore[no-untyped-def]
    assert compare("name", "Nishanth", "Nisha4nth")["color"] == "green"  # the stray digit is dropped
    assert compare("name", "Nishanth", "Nish4nth")["color"] == "red"  # a digit that replaced a letter leaves a gap
    assert codes(compare("name", "Nishanth", "1234")) == ["UNPARSEABLE"]


def test_other_scripts_are_not_supported(compare):  # type: ignore[no-untyped-def]
    hindi = "\u0928\u093f\u0936\u093e\u0902\u0924"
    assert codes(compare("name", "Nishanth", hindi)) == ["UNSUPPORTED_SCRIPT"]
    assert "NON_LATIN_TEXT_IGNORED" in codes(compare("name", "Nishanth", f"Nishanth {hindi}"))


def test_missing_and_oversized_values_are_red(compare):  # type: ignore[no-untyped-def]
    for blank in ("", "   ", "N/A", "nil", None):
        result = compare("name", "Nishanth", blank)
        assert (result["color"], codes(result)) == ("red", ["MISSING_VALUE"])
    assert codes(compare("name", "", "Nishanth")) == ["BASE_MISSING"]
    assert codes(compare("name", "Nishanth", "a " * 150)) == ["TOO_LONG"]
    assert codes(compare("name", "Nishanth", "ab " * 20)) == ["TOO_LONG"]


def test_the_result_has_no_score_and_ignores_ocr_values(compare):  # type: ignore[no-untyped-def]
    plain = compare("name", "kumar sam", "sam kumar")
    shaky = compare("name", "kumar sam", "sam kumar", ocr_confidence=0.5)  # an OCR value changes nothing
    assert shaky == plain
    assert {"score", "confidence", "confidence_level"}.isdisjoint(plain)
    assert (plain["color"], plain["needs_review"]) == ("yellow", True)


def test_highlight_marks_the_replaced_word(compare):  # type: ignore[no-untyped-def]
    result = compare("name", "kumar sam", "sam ramu")
    kinds = {seg["text"]: seg["kind"] for seg in result["highlight"]["candidate"]}
    assert (kinds["ramu"], kinds["sam"]) == ("conflict", "match")
    assert "".join(seg["text"] for seg in result["highlight"]["base"]) == "kumar sam"
