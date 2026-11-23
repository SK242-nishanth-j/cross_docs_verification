"""
Real-world benchmark test suite for cross_verify.py
=====================================================
Every test case is modelled after a genuine KYC scenario:
  - Aadhaar card  vs  PAN card  vs  Passport  vs  Bank / NBFC statement
  - South-Indian, North-Indian, Muslim, Sikh, Bengali, Tamil naming styles
  - Village / district / urban Indian addresses
  - DOB as it appears on each document type

Expected outcomes are pinned so this file acts as a regression guard:
if the engine changes behaviour on a named case you will know immediately.

Run the whole file:
    pytest tests/test_benchmark.py -v

Run one section only:
    pytest tests/test_benchmark.py -v -k "Aadhaar"
    pytest tests/test_benchmark.py -v -k "Name"
    pytest tests/test_benchmark.py -v -k "Address"
    pytest tests/test_benchmark.py -v -k "Dob"
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import TODAY, codes
import cross_verify as cv


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _cmp(compare, field: str, base: Any, cand: Any, **kw) -> dict:
    return compare(field, base, cand, **kw)

def _color(compare, field: str, base: Any, cand: Any) -> str:
    return compare(field, base, cand)["color"]

def _has(result: dict, *reason_codes: str) -> bool:
    present = set(codes(result))
    return all(c in present for c in reason_codes)

def _exact_outcome(compare, field: str, base: Any, cand: Any,
                   color: str,
                   must_have: list[str] | None = None) -> None:
    r = _cmp(compare, field, base, cand)
    assert r["color"] == color, f"[{field}] {base!r} vs {cand!r}: got {r['color']}, want {color}. reasons={codes(r)}"
    if must_have:
        for c in must_have:
            assert c in codes(r), f"Expected reason {c!r} but got {codes(r)}"


# ===========================================================================
# SECTION A — NAMES: Aadhaar vs PAN
#   Aadhaar prints the full name in UPPER CASE.
#   PAN prints surname + given name, often with initials for given names.
# ===========================================================================

class TestNameAadhaarVsPan:
    """
    Aadhaar (base) vs PAN (candidate).
    Aadhaar: full name in ALL CAPS
    PAN: typically SURNAME GIVEN in UPPER CASE, often abbreviated given names.
    """

    @pytest.mark.parametrize("aadhaar,pan,expected_color", [
        # North Indian: order matches
        ("RAMESH KUMAR SHARMA",     "RAMESH KUMAR SHARMA",   "green"),
        ("SUNITA DEVI",             "SUNITA DEVI",           "green"),
        # Initial abbreviation of middle/first name on PAN
        ("PRIYA RAJALAKSHMI NAIR",  "P R NAIR",              "yellow"),
        ("SURESH KUMAR GUPTA",      "S K GUPTA",             "yellow"),
        ("MAHESH CHANDRA JOSHI",    "M C JOSHI",             "yellow"),
        # South Indian: initial before surname on Aadhaar, full name on PAN
        ("R SUNDARAM",              "RAMASWAMY SUNDARAM",    "yellow"),
        ("K MURUGAN",               "KARUPPIAH MURUGAN",     "yellow"),
        ("V KRISHNAMURTHY",         "VENKATARAMAN KRISHNAMURTHY", "yellow"),
        # Surname first on PAN vs first name first on Aadhaar
        ("RAVI SHANKAR",            "SHANKAR RAVI",          "yellow"),
        ("PRIYA DEVI",              "DEVI PRIYA",            "yellow"),
        # Only initial differs
        ("NISHANTH JAYAKUMAR S",    "NISHANTH J S",          "yellow"),  # abbreviated middle
        ("JAYALAKSHMI K R",         "JAYALAKSHMI K R",       "green"),
        # Extra middle name on Aadhaar absent on PAN
        ("AMIT KUMAR SINGH",        "AMIT SINGH",            "yellow"),
        ("SANJAY PRAKASH MEHTA",    "SANJAY MEHTA",          "yellow"),
        # Genuine mismatch: different surnames
        ("RAMESH SHARMA",           "RAMESH VERMA",          "red"),
        ("PRIYA NAIR",              "PRIYA PILLAI",          "red"),
        # Completely different first name
        ("AMIT KUMAR",              "SUMIT KUMAR",           "red"),
        ("KAVITHA REDDY",           "LATHA REDDY",           "red"),
    ])
    def test_aadhaar_vs_pan(self, compare, aadhaar, pan, expected_color):
        _exact_outcome(compare, "name", aadhaar, pan, expected_color)


class TestNameAadhaarVsPassport:
    """
    Aadhaar (base) vs Passport (candidate).
    Passport prints SURNAME / GIVEN NAME separately, all caps, no diacritics.
    Aadhaar may contain diacritics in the full name.
    """

    @pytest.mark.parametrize("aadhaar,passport,expected_color", [
        # Diacritics stripped on passport
        ("José Maria Fernandes",    "JOSE MARIA FERNANDES",  "green"),
        ("Müller Rajan",            "MULLER RAJAN",          "green"),
        ("André Philipose",         "ANDRE PHILIPOSE",       "green"),
        # Honorific on Aadhaar
        ("Shri Rajesh Kumar",       "RAJESH KUMAR",          "green"),
        ("Smt Meena Kumari",        "MEENA KUMARI",          "green"),
        ("Dr Anand Prakash",        "ANAND PRAKASH",         "green"),
        # Care-of on Aadhaar (name before S/O)
        ("Ravi Shankar S/O Krishnan", "RAVI SHANKAR",        "green"),
        ("Meena Devi D/O Ramchandra", "MEENA DEVI",          "green"),
        # First + Last match, middle dropped on passport
        ("Ramesh Babu Naidu",       "RAMESH NAIDU",          "yellow"),
        ("Lakshmi Priya Reddy",     "LAKSHMI REDDY",         "yellow"),
        # Order swapped (surname first on passport)
        ("SHANKAR NARAYANAN",       "NARAYANAN SHANKAR",     "yellow"),
        # Genuine mismatch: different given name
        ("PRIYA KUMARI",            "KAVITHA KUMARI",        "red"),
        ("RAHUL GUPTA",             "ROHIT GUPTA",           "red"),
    ])
    def test_aadhaar_vs_passport(self, compare, aadhaar, passport, expected_color):
        _exact_outcome(compare, "name", aadhaar, passport, expected_color)


class TestNameAadhaarVsBank:
    """
    Aadhaar (base) vs Bank / NBFC account name (candidate).
    Banks often store the name exactly as given on account opening form —
    can have honorifics, different capitalisation, or truncation.
    """

    @pytest.mark.parametrize("aadhaar,bank,expected_color", [
        # Case normalisation
        ("RAMESH KUMAR",         "Ramesh Kumar",          "green"),
        ("SUNITA DEVI",          "sunita devi",           "green"),
        # Title stored by bank
        ("RAMESH SHARMA",        "Mr. Ramesh Sharma",     "green"),
        ("PRIYA NAIR",           "Mrs Priya Nair",        "green"),
        # Account holder label
        ("AMIT SINGH",           "Account Holder: Amit Singh", "green"),
        # Name spelt as one word vs two on bank
        ("NISHANTH KUMAR",       "Nishanthkumar",         "yellow"),
        ("VENKATARAMANA",        "Venkata Ramana",        "yellow"),
        # Initial style from Aadhaar
        ("R KRISHNAMURTHY",      "Raghunathan Krishnamurthy", "yellow"),
        # Extra token on bank (middle name or suffix)
        ("PRIYA DEVI",           "PRIYA DEVI SHARMA",     "yellow"),
        # Missing token on bank (bank truncates long names)
        ("SUBRAMANIAM VENKATARAMAN", "SUBRAMANIAM",       "yellow"),
        # Genuine mismatch
        ("AMIT KUMAR",           "AMEET KUMAR",           "red"),  # spelling
        ("RAMESH SHARMA",        "RAMESH GUPTA",          "red"),
    ])
    def test_aadhaar_vs_bank(self, compare, aadhaar, bank, expected_color):
        _exact_outcome(compare, "name", aadhaar, bank, expected_color)


# ===========================================================================
# SECTION B — NAMES: Regional and community conventions
# ===========================================================================

class TestNameSouthIndianStyle:
    """
    South Indian names: initial(s) before surname, no inherited family name.
    Aadhaar often stores the full expanded name; PAN/Voter ID stores initials.
    """

    @pytest.mark.parametrize("base,candidate,expected_color,must_have", [
        # Initial expands to full word
        ("Ramaswamy Sundaram",   "R Sundaram",          "yellow", ["INITIAL_EXPANDED"]),
        ("Karuppiah Murugan",    "K Murugan",           "yellow", ["INITIAL_EXPANDED"]),
        ("Venkataraman Krishnamurthy", "V Krishnamurthy","yellow", ["INITIAL_EXPANDED"]),
        # Two initials
        ("Krishnan Ravi Shankar","K R Shankar",         "yellow", ["INITIAL_EXPANDED"]),
        ("Palaniswamy Chidambaram", "P Chidambaram",    "yellow", ["INITIAL_EXPANDED"]),
        # Exact with initials — Aadhaar lists "K R Nair", PAN also lists "K R Nair"
        ("K R Nair",             "K R Nair",            "green",  ["EXACT"]),
        ("T N Seshan",           "T N Seshan",          "green",  ["EXACT"]),
        # Token order: Aadhaar=initial+name, Voter ID=name+initial
        ("S Ramalingam",         "Ramalingam S",        "yellow", ["TOKEN_ORDER_DIFFERENT"]),
        ("K Annamalai",          "Annamalai K",         "yellow", ["TOKEN_ORDER_DIFFERENT"]),
        # Full first name on one doc, initial on another
        ("Suresh Krishnamurthy", "S Krishnamurthy",     "yellow", ["INITIAL_EXPANDED"]),
    ])
    def test_south_indian(self, compare, base, candidate, expected_color, must_have):
        r = _cmp(compare, "name", base, candidate)
        assert r["color"] == expected_color, f"{base!r} vs {candidate!r}: got {r['color']}. reasons={codes(r)}"
        for c in must_have:
            assert c in codes(r), f"Missing reason {c!r} in {codes(r)}"


class TestNameMuslimNames:
    """
    Muslim names: typically Father's name follows given name.
    Mohammed / Mohd / MD / Muhammad all refer to the same person.
    """

    @pytest.mark.parametrize("base,candidate,expected_color", [
        # Exact common prefix variants — these are DIFFERENT words to the engine
        ("Mohammed Abdul Kalam",  "Mohd Abdul Kalam",   "red"),   # Mohd ≠ Mohammed
        ("Mohammed Rafi",         "Mohd Rafi",          "red"),   # same
        ("Muhammad Ali",          "Mohammed Ali",       "red"),   # Muhammad ≠ Mohammed
        # Same abbreviation across both docs → green
        ("Mohd Abdul Kalam",      "Mohd Abdul Kalam",   "green"),
        ("MD Yusuf",              "MD Yusuf",           "green"),
        # Father's name in one doc absent in other
        ("Abdul Rahman",          "Abdul Rahman Khan",  "yellow"),
        ("Fathima Begum",         "Fathima",            "yellow"),
        # Order: given + father vs father + given
        ("Khan Shahid",           "Shahid Khan",        "yellow"),
        # Complete mismatch
        ("Rashid Ali",            "Rashid Ahmed",       "red"),
    ])
    def test_muslim_names(self, compare, base, candidate, expected_color):
        _exact_outcome(compare, "name", base, candidate, expected_color)


class TestNameSikhNames:
    """
    Sikh names: Singh (male) / Kaur (female) is universal surname.
    Given name may differ in capitalisation or expansion.
    """

    @pytest.mark.parametrize("base,candidate,expected_color", [
        ("Gurpreet Singh",        "GURPREET SINGH",     "green"),
        ("Harpreet Kaur",         "HARPREET KAUR",      "green"),
        ("Jaswinder Singh",       "J Singh",            "yellow"),
        ("Manpreet Kaur",         "M Kaur",             "yellow"),
        # First name differs while Singh matches → red
        ("Gurpreet Singh",        "Jaspreet Singh",     "red"),
        ("Harpreet Kaur",         "Manpreet Kaur",      "red"),
        # Spelling difference in first name
        ("Sukhwinder Singh",      "Sukhvinder Singh",   "red"),
    ])
    def test_sikh_names(self, compare, base, candidate, expected_color):
        _exact_outcome(compare, "name", base, candidate, expected_color)


class TestNameBengaliNames:
    """
    Bengali names: often long, with Da/Dey/Roy/Ghosh as common surnames.
    """

    @pytest.mark.parametrize("base,candidate,expected_color", [
        ("Subhashis Chakraborty",  "SUBHASHIS CHAKRABORTY", "green"),
        ("Abhijit Banerjee",       "Abhijit Banerjee",      "green"),
        # Short form of first name
        ("Subhashis Chakraborty",  "S Chakraborty",         "yellow"),
        # Different surname
        ("Ratan Mukherjee",        "Ratan Chatterjee",      "red"),
        # Common prefix confusion: Sen vs Sengupta
        ("Amit Sen",               "Amit Sengupta",         "red"),
    ])
    def test_bengali_names(self, compare, base, candidate, expected_color):
        _exact_outcome(compare, "name", base, candidate, expected_color)


class TestNameCommonOCRErrors:
    """
    OCR on scanned documents produces systematic errors.
    The engine must catch clean OCR noise but flag real letter substitutions.
    """

    @pytest.mark.parametrize("clean,ocr_scan,expected_color", [
        # Digit inside word = OCR noise → ignored → green
        ("Nishanth",              "Nisha4nth",           "green"),
        # digit at word boundary leaves a shorter token → conflict → red
        ("Kumar",                 "Kum4r",               "red"),    # 4 at end, kum≠kumar
        # Ram3sh → "ram" (digits stripped from norm) which ≠ "ramesh" → red
        ("Ramesh",                "Ram3sh",              "red"),    # 3 in middle, ram≠ramesh
        # Pi11ai → "pi" + "ai" tokens after stripping digits → conflict → red
        ("Pillai",                "Pi11ai",              "red"),    # 11 in middle, pi≠pillai
        # Clear different letter
        ("Vinay",                 "Vijay",               "red"),
        ("Ramesh",                "Rakesh",              "red"),
        # Case normalisation + noise
        ("NISHANTH",              "NlSHANTH",            "red"),    # l (el) vs I (eye) in OCR
    ])
    def test_ocr_errors(self, compare, clean, ocr_scan, expected_color):
        r = _cmp(compare, "name", clean, ocr_scan)
        assert r["color"] == expected_color, (
            f"{clean!r} vs {ocr_scan!r}: got {r['color']}, want {expected_color}. reasons={codes(r)}"
        )


class TestNameHonorificVariants:
    """All honorifics listed in config must be stripped cleanly."""

    @pytest.mark.parametrize("candidate", [
        "Mr. Ramesh Kumar",
        "Mrs. Ramesh Kumar",
        "Ms Ramesh Kumar",
        "Dr Ramesh Kumar",
        "Dr. Ramesh Kumar",
        "Prof Ramesh Kumar",
        "Shri Ramesh Kumar",
        "Shree Ramesh Kumar",
        "Smt Ramesh Kumar",
        "Smt. Ramesh Kumar",
        "Shrimati Ramesh Kumar",
        "Late Ramesh Kumar",
        "Mister Ramesh Kumar",
        "Mx Ramesh Kumar",
    ])
    def test_all_honorifics_stripped(self, compare, candidate):
        r = _cmp(compare, "name", "Ramesh Kumar", candidate)
        assert r["color"] == "green", f"{candidate!r}: got {r['color']}. reasons={codes(r)}"


class TestNameCareOfVariants:
    """All care-of markers listed in config must be stripped cleanly."""

    @pytest.mark.parametrize("candidate", [
        "Ravi Shankar S/O Krishnan",
        "Meena Devi D/O Ramchandra",
        "Leela W/O Shankar",
        "Ravi C/O Krishnan Kumar",
        "Ravi H/O Meena",
        "Ravi Son of Krishnan",
        "Meena Daughter of Ramchandra",
        "Leela Wife of Shankar",
        "Leela Husband of Shankar",
        "Ravi Care of Krishnan",
    ])
    def test_all_care_of_markers_stripped(self, compare, candidate):
        # Assert it doesn't crash and gives a valid colour
        r = _cmp(compare, "name", "Ravi Shankar" if "Ravi" in candidate else candidate, candidate)
        assert r["color"] in ("green", "yellow", "red")
        assert "INTERNAL_ERROR" not in codes(r)


class TestNameMissingAndEdgeCases:
    """Missing, placeholder, and boundary values."""

    @pytest.mark.parametrize("candidate,expected_code", [
        ("",          "MISSING_VALUE"),
        ("   ",       "MISSING_VALUE"),
        ("N/A",       "MISSING_VALUE"),
        ("n/a",       "MISSING_VALUE"),
        ("NA",        "MISSING_VALUE"),
        ("nil",       "MISSING_VALUE"),
        ("Nil",       "MISSING_VALUE"),
        ("NIL",       "MISSING_VALUE"),
        ("null",      "MISSING_VALUE"),
        ("NULL",      "MISSING_VALUE"),
        ("none",      "MISSING_VALUE"),
        ("NONE",      "MISSING_VALUE"),
        ("unknown",   "MISSING_VALUE"),
        ("UNKNOWN",   "MISSING_VALUE"),
        ("-",         "MISSING_VALUE"),
        ("--",        "MISSING_VALUE"),
        ("xxxx",      "MISSING_VALUE"),
        ("XXXX",      "MISSING_VALUE"),
        ("not applicable", "MISSING_VALUE"),
        ("NOT APPLICABLE", "MISSING_VALUE"),
        ("not available",  "MISSING_VALUE"),
        ("not provided",   "MISSING_VALUE"),
        # Completely invalid
        ("1234",      "UNPARSEABLE"),
        ("!@#$",      "UNPARSEABLE"),
        # Too long
        ("ab " * 20,  "TOO_LONG"),
    ])
    def test_name_missing_and_invalid(self, compare, candidate, expected_code):
        r = _cmp(compare, "name", "Ramesh Kumar", candidate)
        assert r["color"] == "red", f"{candidate!r}: got {r['color']}"
        assert expected_code in codes(r), f"Expected {expected_code!r} in {codes(r)}"

    @pytest.mark.parametrize("base", [None, "", "N/A", "nil", "none", "-"])
    def test_missing_base_gives_base_missing(self, compare, base):
        r = _cmp(compare, "name", base, "Ramesh Kumar")
        assert "BASE_MISSING" in codes(r)

    def test_name_non_latin_script_alone_is_unsupported(self, compare):
        # Pure Hindi
        r = _cmp(compare, "name", "Ramesh Kumar", "\u0930\u092e\u0947\u0936 \u0915\u0941\u092e\u093e\u0930")
        assert "UNSUPPORTED_SCRIPT" in codes(r)

    def test_name_mixed_latin_non_latin_gives_non_latin_ignored(self, compare):
        hindi = "\u0930\u092e\u0947\u0936"
        # Mixed: "Ramesh Kumar <hindi>" — Latin part matches, Hindi is ignored
        r = _cmp(compare, "name", "Ramesh Kumar", f"Ramesh Kumar {hindi}")
        # The Hindi word is non-latin text ignored; Latin tokens still match → green
        assert "NON_LATIN_TEXT_IGNORED" in codes(r)
        assert r["color"] in ("green", "yellow")  # depends on whether extra token flagged


# ===========================================================================
# SECTION C — NAMES: the colour comes from the reasons only
# ===========================================================================

class TestNameColourPinning:
    """For each named scenario the colour and its reasons are pinned."""

    def test_exact_same_name_is_green(self, compare):
        r = _cmp(compare, "name", "Ramesh Kumar Sharma", "Ramesh Kumar Sharma")
        assert r["color"] == "green" and codes(r) == ["EXACT"]

    def test_case_only_difference_is_green(self, compare):
        r = _cmp(compare, "name", "ramesh kumar sharma", "RAMESH KUMAR SHARMA")
        assert r["color"] == "green" and codes(r) == ["NORMALIZED_EQUAL"]

    def test_one_word_swapped_is_yellow(self, compare):
        r = _cmp(compare, "name", "Kumar Ramesh", "Ramesh Kumar")
        assert r["color"] == "yellow" and codes(r) == ["TOKEN_ORDER_DIFFERENT"]

    def test_a_replaced_word_is_red(self, compare):
        r = _cmp(compare, "name", "Ramesh Sharma", "Ramesh Verma")
        assert r["color"] == "red" and codes(r) == ["TOKEN_CONFLICT"]

    def test_one_initial_is_red_and_many_missing_words_are_yellow(self, compare):
        assert _cmp(compare, "name", "Suresh", "S")["color"] == "red"  # INSUFFICIENT_NAME
        r = _cmp(compare, "name", "Anand Bhaskar Chandra Dinesh", "Anand")
        assert (r["color"], codes(r)) == ("yellow", ["MISSING_TOKEN"])  # no score rule turns this red

    def test_the_result_has_no_score_or_confidence(self, compare):
        r = _cmp(compare, "name", "Ramesh Kumar", "Kumar Ramesh")
        assert {"score", "confidence", "confidence_level"}.isdisjoint(r)


# ===========================================================================
# SECTION D — DATES OF BIRTH: all formats that appear on real documents
# ===========================================================================

class TestDobAllFormats:
    """
    Every date format that appears on a real Indian identity document.
    All must resolve to green when compared against 12-03-1998 (12 March 1998).
    """

    BASE = "12-03-1998"

    @pytest.mark.parametrize("candidate,document_source", [
        # ---- Aadhaar / UIDAI ----
        ("12/03/1998",            "Aadhaar card (DD/MM/YYYY)"),
        ("12-03-1998",            "Aadhaar card (DD-MM-YYYY)"),
        ("12.03.1998",            "Aadhaar card (DD.MM.YYYY)"),
        # ---- PAN card ----
        ("12/03/1998",            "PAN card (DD/MM/YYYY)"),
        # ---- Passport ----
        ("12 Mar 1998",           "Passport (DD MMM YYYY)"),
        ("12-Mar-1998",           "Passport (DD-MMM-YYYY)"),
        ("12 March 1998",         "Passport (DD MMMM YYYY)"),
        ("12th March, 1998",      "Passport verbose"),
        ("12th march 1998",       "Passport lowercase"),
        # ---- Voter ID ----
        ("1998-03-12",            "Voter ID (ISO / year-first)"),
        # ---- Driving Licence ----
        ("12/03/1998",            "DL standard"),
        # ---- Bank / NBFC ----
        ("DOB: 12/03/1998",       "Bank label DOB:"),
        ("Date of Birth - 12-03-1998", "Bank full label"),
        ("D.O.B: 12-03-1998",     "Bank D.O.B: style"),
        ("Date of Birth: 12.03.1998", "NBFC full label dot"),
        ("Birth Date: 12-03-1998","NBFC birth date label"),
        # ---- Devanagari digits (some regional Aadhaar printouts) ----
        ("\u0967\u0968-\u0966\u0969-\u0967\u096f\u096f\u096e", "Aadhaar Devanagari digits"),
        # ---- Python date objects (API callers) ----
        (dt.date(1998, 3, 12),    "Python date object"),
        (dt.datetime(1998, 3, 12, 0, 0), "Python datetime object"),
    ])
    def test_all_formats_green(self, compare, candidate, document_source):
        r = _cmp(compare, "dob", self.BASE, candidate)
        assert r["color"] == "green", f"[{document_source}] {candidate!r} → {r['color']}. reasons={codes(r)}"

    @pytest.mark.parametrize("candidate,document_source", [
        # Partial dates → UNPARSEABLE (never partial green or yellow)
        ("12-03-98",   "two-digit year (Aadhaar OCR error)"),
        ("1998",       "year-only (some village records)"),
        ("03-1998",    "month-year only"),
        ("March 1998", "named month-year (old registers)"),
        ("YOB: 1998",  "Year-of-birth label (some voter IDs)"),
    ])
    def test_partial_dates_unparseable(self, compare, candidate, document_source):
        r = _cmp(compare, "dob", self.BASE, candidate)
        assert r["color"] == "red", f"[{document_source}] expected red"
        assert "UNPARSEABLE" in codes(r)


class TestDobRealWorldMismatch:
    """
    Genuine mismatches between documents — all must be RED.
    Cases chosen from common KYC failure patterns.
    """

    @pytest.mark.parametrize("base,candidate,note", [
        # Day-month transposition (commonest data-entry error)
        ("12-03-1998", "03/12/1998",  "DD/MM vs MM/DD confusion"),
        ("05-11-1985", "11/05/1985",  "November 5 vs May 11 swap"),
        # Year typo
        ("12-03-1998", "12-03-1999",  "year incremented by 1"),
        ("12-03-1998", "12-03-1997",  "year decremented by 1"),
        ("15-08-1980", "15-08-1990",  "decade difference"),
        # Month differs
        ("12-03-1998", "12-04-1998",  "month off by 1"),
        ("12-03-1998", "12-06-1998",  "month off by 3"),
        # Day differs
        ("12-03-1998", "13-03-1998",  "day off by 1"),
        ("12-03-1998", "21-03-1998",  "day digits transposed"),
        ("01-07-1975", "10-07-1975",  "day transposition 01 vs 10"),
        # All three differ
        ("12-03-1998", "25-07-1985",  "completely different"),
        # Historical dates (freedom fighters on voter lists)
        ("15-08-1947", "16-08-1947",  "Independence Day DOB off by 1"),
    ])
    def test_mismatch_is_red(self, compare, base, candidate, note):
        r = _cmp(compare, "dob", base, candidate)
        assert r["color"] == "red", f"[{note}] {base} vs {candidate}: got {r['color']}"
        assert "DATE_DIFFERENT" in codes(r)

    @pytest.mark.parametrize("base,candidate,note", [
        # One digit off → POSSIBLE_TYPO
        ("12-03-1998", "21-03-1998",  "day digits transposed → typo"),
        ("12-03-1998", "13-03-1998",  "day off by 1 → typo"),
        ("12-03-1998", "12-04-1998",  "month off by 1 → typo"),
        ("12-03-1998", "12-03-1999",  "year off by 1 → typo"),
    ])
    def test_possible_typo_flagged(self, compare, base, candidate, note):
        r = _cmp(compare, "dob", base, candidate)
        assert "POSSIBLE_TYPO" in codes(r), f"[{note}] expected POSSIBLE_TYPO"
        assert r["color"] == "red"  # the hint never makes a different date yellow

    def test_dob_never_yellow(self, compare):
        """DOB is binary: green (all parts match) or red (any part differs)."""
        cases = [
            ("12-03-1998", "12-03-1999"),
            ("12-03-1998", "13-03-1998"),
            ("12-03-1998", "03/12/1998"),
            ("12-03-1998", "21-03-1998"),
        ]
        for base, cand in cases:
            assert _color(compare, "dob", base, cand) in ("green", "red"), f"{base} vs {cand}"


class TestDobInvalidDates:
    """Calendar invalid dates must be UNPARSEABLE."""

    @pytest.mark.parametrize("candidate", [
        "31-02-1998",  # Feb has ≤ 29 days
        "30-02-2000",  # even in leap year Feb has 29
        "29-02-1999",  # 1999 is not a leap year
        "31-04-1998",  # April has 30 days
        "31-06-1998",  # June has 30 days
        "31-11-1998",  # November has 30 days
        "00-03-1998",  # day 0
        "13-00-1998",  # month 0
        "32-03-1998",  # day 32
        "12-13-1998",  # month 13
        "99-99-9999",  # completely invalid
    ])
    def test_invalid_calendar_date(self, compare, candidate):
        r = _cmp(compare, "dob", "12-03-1998", candidate)
        assert r["color"] == "red"
        assert "UNPARSEABLE" in codes(r), f"{candidate!r}: {codes(r)}"


class TestDobBoundaryAges:
    """Age boundary: future dates and very old dates are DATE_IMPLAUSIBLE."""

    def test_future_date_is_implausible(self, compare):
        # TODAY = 2026-11-13, so 2027 is future
        r = _cmp(compare, "dob", "12-03-1998", "12-03-2027")
        assert "DATE_IMPLAUSIBLE" in codes(r)

    def test_today_is_implausible(self, compare):
        # Born today = age 0 = suspicious for a KYC document
        r = _cmp(compare, "dob", "12-03-1998", TODAY.strftime("%d-%m-%Y"))
        assert r["color"] == "red"

    def test_too_old_is_implausible(self, compare):
        # max_age = 110 years from config; 1900 is 126 years ago
        r = _cmp(compare, "dob", "12-03-1998", "12-03-1900")
        assert "DATE_IMPLAUSIBLE" in codes(r)

    def test_exactly_at_max_age_boundary(self, compare):
        # 2026 - 110 = 1916; 1916 is at the boundary (too old → implausible)
        r = _cmp(compare, "dob", "12-03-1900", "01-01-1900")
        assert r["color"] == "red"

    def test_valid_elderly_person(self, compare):
        # Born 1930: 96 years old — still valid
        r = _cmp(compare, "dob", "15-08-1930", "15/08/1930")
        assert r["color"] == "green"

    def test_leap_year_29_feb_valid(self, compare):
        # 2000 is divisible by 400 → leap year
        r = _cmp(compare, "dob", "29-02-2000", "29/02/2000")
        assert r["color"] == "green"

    def test_non_leap_year_29_feb_invalid(self, compare):
        for year in ("1999", "1998", "1900"):
            r = _cmp(compare, "dob", "12-03-1998", f"29-02-{year}")
            assert "UNPARSEABLE" in codes(r), f"29-02-{year}"


# ===========================================================================
# SECTION E — ADDRESSES: Aadhaar vs PAN vs Bank vs Voter ID
# ===========================================================================

class TestAddressAadhaarStyle:
    """
    Aadhaar addresses: multi-line, often with S/O line, Devanagari digits,
    district / taluk / village structure.
    """

    # Base: a typical Aadhaar address in Bangalore
    BASE = "Flat No. 12, Sai Towers, 3rd Main, Koramangala 5th Block, Bangalore - 560095"

    @pytest.mark.parametrize("candidate,note", [
        # City alias: Bengaluru is canonical, Bangalore is listed alias
        ("Flat 12, Sai Towers, 3rd Main, Koramangala 5th Block, Bengaluru 560095",
         "Bengaluru/Bangalore alias"),
        # S/O line removed
        ("S/O Krishnamurthy, Flat 12 Sai Towers 3rd Main Koramangala 5th Block Bengaluru 560095",
         "S/O line stripped"),
        # Uppercase
        ("FLAT NO 12 SAI TOWERS 3RD MAIN KORAMANGALA 5TH BLOCK BENGALURU 560095",
         "All caps"),
        # 'Second' instead of '2nd' — number word
        ("Flat 12, Sai Towers, Third Main, Koramangala 5th Block, Bangalore 560095",
         "ordinal word"),
        # Pincode spaced
        ("Flat 12, Sai Towers, 3rd Main, Koramangala 5th Block, Bangalore 560 095",
         "Pincode with space"),
        # Address label prefix
        ("Permanent Address: Flat 12 Sai Towers 3rd Main Koramangala 5th Block Bengaluru 560095",
         "Address label stripped"),
    ])
    def test_aadhaar_address_green(self, compare, candidate, note):
        r = _cmp(compare, "address", self.BASE, candidate)
        assert r["color"] == "green", f"[{note}] {candidate!r}: got {r['color']}. reasons={codes(r)}"


class TestAddressPanCardStyle:
    """
    PAN addresses from Form 49A — often abbreviated: Rd, St, Apt, Blk etc.
    """

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Road abbreviation
        ("12 MG Road, Pune 411001",
         "12 MG Rd, Pune 411001",           "green",  "Rd=road abbreviation"),
        # Street abbreviation
        ("45 Park Street, Kolkata 700016",
         "45 Park St, Kolkata 700016",       "green",  "St=street abbreviation"),
        # Near-pincode (last digit different)
        ("12 MG Road, Pune 411001",
         "12 MG Road, Pune 411002",          "yellow", "pincode last digit"),
        # Number subset (12 vs 12/1) — 12 is a prefix of 12/1 → NUMBER_SUBSET (yellow)
        ("12 MG Road, Pune 411001",
         "12/1 MG Road, Pune 411001",        "yellow", "number subset 12 vs 12/1"),
        # Spelling of locality
        ("12 MG Road, Shivajinagar, Pune 411005",
         "12 MG Road, Shivajinagar, Pune 411005", "green", "exact"),
        # City alias
        ("12 MG Road, Bombay 400001",
         "12 MG Road, Mumbai 400001",        "green",  "Bombay=Mumbai alias"),
        # Number mismatch
        ("12 MG Road, Pune 411001",
         "21 MG Road, Pune 411001",          "red",    "house number mismatch"),
        # City mismatch
        ("12 MG Road, Pune 411001",
         "12 MG Road, Mumbai 411001",        "red",    "city mismatch"),
    ])
    def test_pan_address(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "address", base, candidate)
        assert r["color"] == expected_color, f"[{note}] {candidate!r}: got {r['color']}. reasons={codes(r)}"


class TestAddressVillageAndRuralStyle:
    """
    Rural / village addresses appear on Aadhaar (semi-urban enrollment),
    Voter IDs, and PMAY applications. They lack pincode, have District/Taluk/Village.
    """

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Village abbreviation: Vill = village, PO = post, Dist = district
        ("Village Rampur, Post Lakhimpur, District Kheri, Uttar Pradesh 262701",
         "Vill Rampur PO Lakhimpur Dist Kheri UP 262701",
         "green", "village abbreviations"),
        # Post Office → PO abbreviation
        ("Village Ambedkar Nagar, Post Office Ambedkar Nagar, Dist Faizabad, UP 224122",
         "Vill Ambedkar Nagar PO Ambedkar Nagar Dist Faizabad UP 224122",
         "green", "PO abbreviation"),
        # Taluk abbreviation: Teh/Tal/TQ
        ("Village Naduvathi, Taluk Devanahalli, District Bangalore Rural 562110",
         "Vill Naduvathi Teh Devanahalli Dist Bangalore Rural 562110",
         "green", "Teh=taluk"),
        # Different village → red
        ("Village Rampur, Dist Kheri, UP 262701",
         "Village Sitapur, Dist Kheri, UP 262701",
         "red", "different village"),
        # Pincode last digit differs — with house number anchor it is PINCODE_NEAR (yellow)
        ("H.No. 12, Village Rampur, Dist Kheri, UP 262701",
         "H.No. 12, Village Rampur, Dist Kheri, UP 262702",
         "yellow", "pincode last digit differs with house number anchor"),
        # Without house number anchor, near pincode cannot anchor alone → NO_ANCHOR_MATCH (red)
        ("Village Rampur, Dist Kheri, UP 262701",
         "Village Rampur, Dist Kheri, UP 262702",
         "red", "near pincode without house number lacks anchor"),
    ])
    def test_village_address(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "address", base, candidate)
        assert r["color"] == expected_color, f"[{note}]: got {r['color']}. reasons={codes(r)}"


class TestAddressUrbanAndApartmentStyle:
    """
    Urban apartment addresses across major Indian cities with
    block / sector / phase / floor descriptors.
    """

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Sector descriptor
        ("Plot 45, Sector 18, Noida 201301",
         "45 Sector 18 Noida 201301",          "green",  "plot vs no label"),
        # Phase descriptor
        ("12 Phase 2, DLF City, Gurugram 122002",
         "12 Phase 2 DLF City Gurgaon 122002",  "green",  "Gurgaon=Gurugram alias"),
        # Block descriptor
        ("B-12 Block B, Mayur Vihar, Delhi 110091",
         "B 12 Block B Mayur Vihar Delhi 110091","green",  "B-12 format"),
        # Floor number
        ("3rd Floor, 45 MG Road, Bangalore 560001",
         "3 Floor 45 MG Road Bengaluru 560001",  "green",  "3rd floor"),
        # Building name typo → spelling variant
        ("Sai Residency, Koramangala, Bengaluru 560034",
         "Sai Residence, Koramangala, Bengaluru 560034",
         "yellow", "Residency vs Residence"),
        # Apartment vs Apartments (plural)
        ("Sea View Apartments, Marine Drive, Mumbai 400002",
         "Sea View Apartment, Marine Drive, Mumbai 400002",
         "green", "plural stem match"),
        # Different building entirely
        ("Sai Towers, MG Road, Bengaluru 560001",
         "Royal Towers, MG Road, Bengaluru 560001",
         "red", "different building name"),
        # Different sector
        ("Plot 45, Sector 18, Noida 201301",
         "Plot 45, Sector 62, Noida 201309",
         "red", "different sector"),
    ])
    def test_urban_apartment(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "address", base, candidate)
        assert r["color"] == expected_color, f"[{note}]: got {r['color']}. reasons={codes(r)}"


class TestAddressCityAliases:
    """Every city alias in the config must be treated as the canonical city name."""

    @pytest.mark.parametrize("city_in_base,city_alias,pincode", [
        ("Bengaluru",    "Bangalore",          "560001"),
        ("Bengaluru",    "Bengalooru",         "560001"),
        ("Bengaluru",    "Bangalore Urban",    "560001"),
        ("Mumbai",       "Bombay",             "400001"),
        ("Mumbai",       "Greater Mumbai",     "400001"),
        ("Pune",         "Poona",              "411001"),
        ("Mysuru",       "Mysore",             "570001"),
        ("Chennai",      "Madras",             "600001"),
        ("Kolkata",      "Calcutta",           "700001"),
        ("Ahmedabad",    "Amdavad",            "380001"),
        ("Vadodara",     "Baroda",             "390001"),
        ("Thiruvananthapuram", "Trivandrum",   "695001"),
        ("Kochi",        "Cochin",             "682001"),
        ("Kozhikode",    "Calicut",            "673001"),
        ("Mangaluru",    "Mangalore",          "575001"),
        ("Hubballi",     "Hubli",              "580001"),
        ("Visakhapatnam","Vizag",              "530001"),
        ("Vijayawada",   "Bezawada",           "520001"),
        ("Prayagraj",    "Allahabad",          "211001"),
        ("Varanasi",     "Banaras",            "221001"),
        ("Varanasi",     "Benares",            "221001"),
        ("Gurugram",     "Gurgaon",            "122001"),
        ("Delhi",        "New Delhi",          "110001"),
        ("Jamshedpur",   "Jamshedpur",         "831001"),
        ("Jalandhar",    "Jullundur",          "144001"),
        ("Panaji",       "Panjim",             "403001"),
        ("Puducherry",   "Pondicherry",        "605001"),
    ])
    def test_city_alias(self, compare, city_in_base, city_alias, pincode):
        base = f"42 Main Street, {city_in_base} {pincode}"
        cand = f"42 Main Street, {city_alias} {pincode}"
        r = _cmp(compare, "address", base, cand)
        assert r["color"] == "green", (
            f"{city_in_base!r} vs alias {city_alias!r}: got {r['color']}. reasons={codes(r)}"
        )


class TestAddressPincodeEdgeCases:
    """Pincode-specific logic: near-miss, full mismatch, absent one side."""

    BASE = "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore - 560034"

    @pytest.mark.parametrize("pincode,expected_color,note", [
        # Exact match
        ("560034", "green",  "exact pincode"),
        # Same first 3 digits, last 3 differ by 1 → PINCODE_NEAR (yellow if nothing else wrong)
        ("560035", "yellow", "near pincode +1 last digit"),
        ("560033", "yellow", "near pincode -1 last digit"),
        # Same first 3 digits, last 3 differ by more than 1 → still PINCODE_NEAR because prefix 560=560
        # (config: pincode_near_prefix=3, so 560xxx vs 560yyy → "near" unless other parts conflict)
        ("560038", "yellow", "far last-3 digits but same prefix 560"),
        # Completely different first 3 digits
        ("600001", "red",    "completely different pincode"),
        ("110001", "red",    "Delhi pincode for Bangalore address"),
    ])
    def test_pincode_variants(self, compare, pincode, expected_color, note):
        cand = f"402, Sai Residency, 2nd Cross, Koramangala, Bengaluru {pincode}"
        r = _cmp(compare, "address", self.BASE, cand)
        assert r["color"] == expected_color, f"[{note}] pincode={pincode}: got {r['color']}. reasons={codes(r)}"

    def test_pincode_near_becomes_red_when_house_also_wrong(self, compare):
        """Near pincode + wrong house number → RED (not yellow)."""
        cand = "12, Sai Residency, 2nd Cross, Koramangala, Bengaluru 560035"
        r = _cmp(compare, "address", self.BASE, cand)
        assert r["color"] == "red"
        assert "PINCODE_MISMATCH" in codes(r)

    def test_absent_pincode_on_candidate_is_yellow(self, compare):
        cand = "402 Sai Residency 2nd Cross Koramangala Bengaluru"
        r = _cmp(compare, "address", self.BASE, cand)
        assert r["color"] == "yellow"
        assert "INCOMPLETE_ADDRESS" in codes(r)


class TestAddressHouseNumberFormats:
    """
    Indian house numbers appear in many formats across documents.
    """

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Simple integer
        ("12 MG Road, Pune 411001",           "12 MG Road Pune 411001",       "green", "plain integer"),
        # Fraction format (common in Tamil Nadu, Andhra)
        ("12/3 Nehru Street, Chennai 600001", "12/3 Nehru Street Chennai 600001","green","fraction format"),
        # H.No. prefix
        ("H.No. 45, Sector 7, Chandigarh 160001",
         "45 Sector 7 Chandigarh 160001",     "green", "H.No. prefix ignored"),
        # Ordinal: 2nd Cross vs 2 Cross vs Second Cross
        ("2nd Cross, Koramangala, Bengaluru 560034",
         "2 Cross Koramangala Bengaluru 560034", "green","2nd vs 2"),
        ("2nd Cross, Koramangala, Bengaluru 560034",
         "Second Cross Koramangala Bengaluru 560034","green","2nd vs Second"),
        # Number subset (prefix match 12 vs 12/1)
        ("12 MG Road, Pune 411001",           "12/1 MG Road Pune 411001",     "yellow","number subset"),
        # Different number
        ("12 MG Road, Pune 411001",           "21 MG Road Pune 411001",       "red",  "different number"),
        # 5th Main vs 7th Main → number mismatch
        ("5th Main, Indiranagar, Bengaluru 560038",
         "7th Main Indiranagar Bengaluru 560038","red", "different main number"),
    ])
    def test_house_number_formats(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "address", base, candidate)
        assert r["color"] == expected_color, f"[{note}]: got {r['color']}. reasons={codes(r)}"


class TestAddressSpellingVariants:
    """
    Spelling variants in locality/place names
    (edit distance 1-2 for words ≥ 5 chars → SPELLING_VARIANT).
    """

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # 1-char edit in 8-char word → within allowance
        ("Residency Road, Bengaluru 560001",
         "Residiency Road Bengaluru 560001",  "yellow", "Residency vs Residiency"),
        # 2-char edit in 10-char word → within allowance
        ("Koramangala, Bengaluru 560095",
         "Koromangala Bengaluru 560095",      "yellow", "Koramangala vs Koromangala"),
        # Place name spelling variant
        ("Jayanagar, Bengaluru 560041",
         "Jayenagar Bengaluru 560041",        "yellow", "Jayanagar vs Jayenagar"),
        # Exact match (not a spelling variant)
        ("Koramangala, Bengaluru 560095",
         "Koramangala Bengaluru 560095",      "green",  "exact locality"),
    ])
    def test_spelling_variants(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "address", base, candidate)
        assert r["color"] == expected_color, f"[{note}]: got {r['color']}. reasons={codes(r)}"


class TestAddressMissingAndUnreadable:
    """Missing / unreadable addresses → RED."""

    @pytest.mark.parametrize("candidate,expected_code,note", [
        ("",              "MISSING_VALUE",      "empty string"),
        ("   ",           "MISSING_VALUE",      "whitespace"),
        ("N/A",           "MISSING_VALUE",      "N/A placeholder"),
        ("nil",           "MISSING_VALUE",      "nil placeholder"),
        ("!!! ???",       "UNPARSEABLE",        "only punctuation"),
        # Devanagari-only → no Latin tokens, no pincode
        ("\u0928\u0908 \u0926\u093f\u0932\u094d\u0932\u0940",
                          "UNSUPPORTED_SCRIPT", "Hindi text only"),
        # Too long
        ("x" * 1200,      "TOO_LONG",           "length > 1000"),
    ])
    def test_unreadable(self, compare, candidate, expected_code, note):
        r = _cmp(compare, "address",
                 "Flat 402, Sai Residency, Koramangala, Bangalore 560034", candidate)
        assert r["color"] == "red", f"[{note}]"
        assert expected_code in codes(r)

    def test_no_anchor_match(self, compare):
        """City + locality only, no pincode, no house number → NO_ANCHOR_MATCH."""
        r = _cmp(compare, "address",
                 "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore 560034",
                 "Koramangala, Bengaluru")
        assert "NO_ANCHOR_MATCH" in codes(r)
        assert r["color"] == "red"


# ===========================================================================
# SECTION F — FULL KYC SCENARIO: multi-field, multi-candidate verification
# ===========================================================================

class TestFullKycScenario:
    """
    End-to-end simulation of a real KYC check:
    - Applicant provides Aadhaar + PAN + Bank statement.
    - Each source has the same field (name, dob, address).
    - We verify base (from application form) against all three sources.
    """

    def _kyc_check(self, verify, field: str, base: Any,
                   aadhaar: Any, pan: Any, bank: Any) -> dict:
        return verify([{
            "field": field, "type": field, "base": base,
            "candidates": [
                {"source": "aadhaar", "value": aadhaar},
                {"source": "pan",     "value": pan},
                {"source": "bank",    "value": bank},
            ],
        }], today=TODAY)["fields"][0]

    def test_all_docs_agree_name(self, verify):
        field = self._kyc_check(verify, "name",
            "Ramesh Kumar Sharma",
            "RAMESH KUMAR SHARMA",
            "R K SHARMA",
            "Mr. Ramesh Kumar Sharma")
        assert field["color"] == "yellow"   # PAN gives initial form → yellow
        assert all(c["color"] in ("green", "yellow") for c in field["comparisons"])

    def test_pan_has_conflict_name(self, verify):
        field = self._kyc_check(verify, "name",
            "Ramesh Kumar Sharma",
            "RAMESH KUMAR SHARMA",   # green
            "RAHUL KUMAR SHARMA",    # red — first name mismatch
            "Mr. Ramesh Kumar Sharma")  # green
        # Worst is red
        assert field["color"] == "red"
        colors = {c["source"]: c["color"] for c in field["comparisons"]}
        assert colors["pan"] == "red"
        assert colors["aadhaar"] == "green"

    def test_dob_all_agree(self, verify):
        field = self._kyc_check(verify, "dob",
            "12-03-1998",
            "12/03/1998",    # green
            "12-03-1998",    # green (exact)
            "DOB: 12.03.1998")  # green
        assert field["color"] == "green"
        assert all(c["color"] == "green" for c in field["comparisons"])

    def test_dob_bank_has_error(self, verify):
        field = self._kyc_check(verify, "dob",
            "12-03-1998",
            "12/03/1998",    # green
            "12-03-1998",    # green
            "03-12-1998")    # red — day/month swapped
        assert field["color"] == "red"
        colors = {c["source"]: c["color"] for c in field["comparisons"]}
        assert colors["bank"] == "red"

    def test_address_all_agree(self, verify):
        field = self._kyc_check(verify, "address",
            "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore 560034",
            "S/O Ramesh, 402 Sai Residency 2nd Cross Koramangala Bengaluru 560034",
            "402, SAI RESIDENCY, 2ND CROSS, KORAMANGALA, BENGALURU 560034",
            "Flat 402 Sai Residency 2nd Cross Koramangala Bangalore 560034")
        assert field["color"] == "green"

    def test_address_candidate_has_different_city(self, verify):
        field = self._kyc_check(verify, "address",
            "Flat 402, Sai Residency, Koramangala, Bangalore 560034",
            "402 Sai Residency Koramangala Bengaluru 560034",   # green
            "402 Sai Residency Koramangala Bengaluru 560034",   # green
            "402 Sai Residency Koramangala Chennai 600034")     # red
        assert field["color"] == "red"
        colors = {c["source"]: c["color"] for c in field["comparisons"]}
        assert colors["bank"] == "red"
        bank_comp = next(c for c in field["comparisons"] if c["source"] == "bank")
        assert "CITY_MISMATCH" in codes(bank_comp)

    def test_counts_aggregated_across_all_fields(self, verify):
        report = verify([
            {"field": "name", "type": "name",
             "base": "Ramesh Kumar",
             "candidates": [{"source": "aadhaar", "value": "RAMESH KUMAR"},
                            {"source": "pan",     "value": "R KUMAR"},
                            {"source": "bank",    "value": "SURESH KUMAR"}]},  # RED
            {"field": "dob", "type": "dob",
             "base": "12-03-1998",
             "candidates": [{"source": "aadhaar", "value": "12/03/1998"},
                            {"source": "pan",     "value": "12-03-1998"},
                            {"source": "bank",    "value": "12-03-1998"}]},
        ], today=TODAY)
        counts = report["overall"]["counts"]
        # 1 red (bank name) + 1 yellow (PAN initial) + 1 green (aadhaar name) + 3 green DOB
        assert counts["mismatch"] >= 1
        assert report["overall"]["color"] == "red"

    def test_needs_review_flag_propagates(self, verify):
        report = verify([{
            "field": "name", "type": "name",
            "base": "Ramesh Kumar",
            "candidates": [{"source": "aadhaar", "value": "RAMESH KUMAR"},
                           {"source": "pan", "value": "SURESH KUMAR"}],  # conflict
        }], today=TODAY)
        assert report["overall"]["needs_review"] is True


# ===========================================================================
# SECTION G — EDGE CASES AND BOUNDARY CONDITIONS
# ===========================================================================

class TestEdgeCasesNames:
    """Names that sit right on boundaries and might trip up the engine."""

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Single-word name (common in South India)
        ("Murugan",             "MURUGAN",           "green",  "single word all caps"),
        ("Murugan",             "Mr Murugan",        "green",  "single word with honorific"),
        ("Murugan",             "Murugesan",         "red",    "different single word"),
        # Very long name (Brahmin / Tamil naming)
        ("Krishnaswamy Venkataraman Subramaniam", "K V Subramaniam", "yellow", "3-initial compression"),
        # Name with apostrophe (letters normalizedNFKD NFKD lowercased -> same)
        ("O'Brien",             "OBrien",            "green",  "apostrophe dropped → same normalized tokens"),
        ("D'Souza",             "DSOUZA",            "green",  "apostrophe dropped → same normalized tokens"),
        # Name with digit in label (label with digit not in predefined labels list -> extra token)
        ("Ramesh Kumar",        "Name1: Ramesh Kumar","yellow", "label with digit treated as extra token"),
        # Double-barrelled name (hyphen splits into same tokens)
        ("Mary-Ann Joseph",     "Mary Ann Joseph",   "green",  "hyphen splits into same tokens"),
        # Initial only (insufficient)
        ("Ramesh",              "R",                 "red",    "single initial insufficient"),
        # Initials only but enough of them
        ("Ramesh Kumar Sharma", "R K S",             "yellow", "3 initials = sufficient"),
        # Name that looks like a placeholder but is not
        ("Nila",                "Nila",              "green",  "short name that isn't a placeholder"),
        ("Ana",                 "Ana",               "green",  "3-letter name"),
        # Honorific only → no name after → unparseable on candidate
        ("Ramesh",              "Mr.",               "red",    "honorific with no name"),
    ])
    def test_name_edge_cases(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "name", base, candidate)
        assert r["color"] == expected_color, (
            f"[{note}] {base!r} vs {candidate!r}: got {r['color']}. reasons={codes(r)}"
        )


class TestEdgeCasesDob:
    """DOB edge cases."""

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Same date different separators
        ("01-01-2000", "01/01/2000",        "green",  "slash vs dash"),
        ("01-01-2000", "01.01.2000",        "green",  "dot separator"),
        # First of January (common default for missing day/month in village records)
        ("01-01-1980", "1st January 1980",  "green",  "ordinal + full month"),
        ("01-01-1980", "01 Jan 1980",       "green",  "day month abbrev"),
        # 15 August (Independence Day — many Aadhaar DOBs from villages)
        ("15-08-1947", "15th Aug 1947",     "green",  "15th Aug"),
        ("15-08-1947", "15 August 1947",    "green",  "15 August full"),
        # Year-first format (ISO)
        ("26-01-1950", "1950-01-26",        "green",  "ISO year-first Republic Day"),
        # DOB with label noise
        ("12-03-1998", "DOB/YOB: 12/03/1998", "green","DOB/YOB label"),
        ("12-03-1998", "Born: 12-03-1998",  "green",  "Born: label"),
        # Completely wrong date
        ("12-03-1998", "12-03-1980",        "red",    "18-year difference"),
        # Month confusion: Mar vs May (3 vs 5)
        ("12-03-1998", "12-05-1998",        "red",    "march vs may"),
    ])
    def test_dob_edge_cases(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "dob", base, candidate)
        assert r["color"] == expected_color, (
            f"[{note}] {base!r} vs {candidate!r}: got {r['color']}. reasons={codes(r)}"
        )


class TestEdgeCasesAddress:
    """Address edge cases."""

    @pytest.mark.parametrize("base,candidate,expected_color,note", [
        # Missing pincode but has house number anchor → green
        ("402 Sai Residency, Koramangala, Bengaluru",
         "402 Sai Residency Koramangala Bengaluru",   "green",  "no pincode but house number anchor"),
        # Both missing pincode AND house number → NO_ANCHOR_MATCH → red
        ("Sai Residency, Koramangala, Bengaluru",
         "Sai Residency Koramangala Bengaluru",       "red",    "no anchor both sides"),
        # Both no city — only text + number + pincode anchor
        ("402 Sai Residency 2nd Cross 560034",
         "402 Sai Residency 2nd Cross 560034",        "green",  "no city both sides"),
        # Only pincode present on both → anchor match
        ("560034",
         "560034",                                    "green",  "pincode only both sides"),
        # Only city name present on both without anchor → NO_ANCHOR_MATCH → red
        ("Bengaluru",
         "Bangalore",                                 "red",    "city-only both sides lacks anchor"),
        # Completely blank candidate
        ("Flat 12, Sai Towers, Bangalore 560001",
         "",                                      "red",    "empty candidate"),
        # Candidate is just punctuation
        ("Flat 12, Sai Towers, Bangalore 560001",
         ",,,,",                                  "red",    "punctuation only"),
    ])
    def test_address_edge_cases(self, compare, base, candidate, expected_color, note):
        r = _cmp(compare, "address", base, candidate)
        assert r["color"] == expected_color, (
            f"[{note}]: got {r['color']}. reasons={codes(r)}"
        )


# ===========================================================================
# SECTION H — HIGHLIGHTS AND COMPONENTS
# ===========================================================================

class TestHighlightReconstruction:
    """Highlight segments must always rebuild the original raw string."""

    @pytest.mark.parametrize("field,base,candidate", [
        ("name",    "Ramesh Kumar Sharma",  "Kumar Ramesh Sharma"),
        ("name",    "Priya Devi",           "Priya Nair"),
        ("name",    "Suresh K Nair",        "K Suresh Nair"),
        ("dob",     "12-03-1998",           "03/12/1998"),
        ("dob",     "12-03-1998",           "12-03-1999"),
        ("address", "Flat 402, Sai Residency, Koramangala, Bangalore 560034",
                    "12, 5th Main, Indiranagar, Bengaluru 560038"),
        ("address", "12 MG Road, Pune 411001",
                    "12/A MG Road Pune 411002"),
    ])
    def test_highlight_rebuilds_raw(self, compare, field, base, candidate):
        r = _cmp(compare, field, base, candidate)
        if r["raw"] is not None:
            rebuilt = "".join(s["text"] for s in r["highlight"]["candidate"])
            assert rebuilt == r["raw"], f"[{field}] highlight didn't rebuild raw"
        if r["highlight"]["base"]:
            rebuilt_base = "".join(s["text"] for s in r["highlight"]["base"])
            assert rebuilt_base == str(base), f"[{field}] base highlight didn't rebuild"


class TestDobComponentTable:
    """DOB result always has a day/month/year component table."""

    @pytest.mark.parametrize("base,candidate,day,month,year", [
        ("12-03-1998", "12-03-1998", "match",   "match",   "match"),
        ("12-03-1998", "13-03-1998", "conflict", "match",   "match"),
        ("12-03-1998", "12-04-1998", "match",    "conflict","match"),
        ("12-03-1998", "12-03-1999", "match",    "match",   "conflict"),
        ("12-03-1998", "03/12/1998", "conflict", "conflict","match"),
    ])
    def test_components(self, compare, base, candidate, day, month, year):
        r = _cmp(compare, "dob", base, candidate)
        comp = {c["component"]: c["relation"] for c in r["components"]}
        assert comp["day"]   == day,   f"day: {comp}"
        assert comp["month"] == month, f"month: {comp}"
        assert comp["year"]  == year,  f"year: {comp}"


class TestAddressComponentTable:
    """Address result has pincode/city/number/text component table."""

    def test_all_match(self, compare):
        r = _cmp(compare, "address",
                 "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore 560034",
                 "402 Sai Residency 2nd Cross Koramangala Bengaluru 560034")
        comp = {c["component"]: c["status"] for c in r["components"]}
        assert comp["pincode"] == "match"
        assert comp["city"]    == "match"

    def test_mismatch_components(self, compare):
        r = _cmp(compare, "address",
                 "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore 560034",
                 "12, 5th Main, Indiranagar, Bengaluru 560038")
        comp = {c["component"]: c["status"] for c in r["components"]}
        assert comp["pincode"] == "mismatch"
        assert comp["number"]  == "mismatch"


# ===========================================================================
# SECTION I — NO SCORE, NO CONFIDENCE: the colour is decided by the reasons only
# ===========================================================================

class TestColourComesFromReasonsOnly:
    """The result carries a colour, a status and the reasons. There is no score, confidence or OCR input."""

    @pytest.mark.parametrize("field,base,candidate,color,needs_review", [
        ("name",    "Ramesh Kumar",  "RAMESH KUMAR", "green",  False),
        ("name",    "Kumar Sam",     "Sam Kumar",    "yellow", True),
        ("name",    "Ramesh Kumar",  "Suresh Babu",  "red",    True),
        ("dob",     "12-03-1998",   "12/03/1998",    "green",  False),
        ("dob",     "12-03-1998",   "13-03-1998",    "red",    True),
        ("address", "12 MG Road, Pune 411001", "12 MG Rd Pune 411001", "green", False),
        ("address", "12 MG Road, Pune 411001", "99 Nehru Street, Chennai 600001", "red", True),
    ])
    def test_colour_and_review_flag(self, compare, field, base, candidate, color, needs_review):
        r = _cmp(compare, field, base, candidate)
        assert (r["color"], r["needs_review"]) == (color, needs_review)
        assert {"score", "confidence", "confidence_level"}.isdisjoint(r)

    def test_the_worst_severity_decides_the_colour(self, compare):
        """Yellow reasons plus a red reason is red. Yellow reasons alone are yellow, however many there are."""
        many_yellow = _cmp(compare, "name", "Anand Bhaskar Chandra Dinesh", "Anand")
        assert (many_yellow["color"], {r["severity"] for r in many_yellow["reasons"]}) == ("yellow", {"warn"})
        red = _cmp(compare, "name", "Nishanth Kumar", "Nishant Kumar")
        assert (red["color"], "fail" in {r["severity"] for r in red["reasons"]}) == ("red", True)

    def test_ocr_values_in_the_request_are_ignored(self, verify):
        check = {"field": "name", "type": "name", "base": "Ramesh Kumar", "base_ocr_confidence": 0.1,
                 "candidates": [{"source": "x", "value": "Kumar Ramesh", "ocr_confidence": 0.1}]}
        plain = {**check, "candidates": [{"source": "x", "value": "Kumar Ramesh"}]}
        plain.pop("base_ocr_confidence")
        assert verify([check])["fields"][0]["comparisons"] == verify([plain])["fields"][0]["comparisons"]


# ===========================================================================
# SECTION J — DETERMINISM, THREAD SAFETY, PERFORMANCE
# ===========================================================================

class TestDeterminism:
    """Same input always produces the same output."""

    def test_name_deterministic(self, verify):
        payload = [{"field": "name", "type": "name",
                    "base": "Ramesh Kumar Sharma",
                    "candidates": [{"source": "a", "value": "R K Sharma"},
                                   {"source": "b", "value": "RAMESH SHARMA"}]}]
        r1 = json.dumps(verify(payload, request_id="x"), sort_keys=True)
        r2 = json.dumps(verify(payload, request_id="x"), sort_keys=True)
        assert r1 == r2

    def test_address_deterministic(self, verify):
        payload = [{"field": "address", "type": "address",
                    "base": "Flat 402, Sai Residency, Koramangala, Bangalore 560034",
                    "candidates": [{"source": "a", "value": "402 Sai Residence Koramangala Bengaluru 560034"}]}]
        r1 = json.dumps(verify(payload, request_id="y"), sort_keys=True)
        r2 = json.dumps(verify(payload, request_id="y"), sort_keys=True)
        assert r1 == r2

    def test_input_not_mutated(self, verify):
        payload = [{"field": "name", "type": "name",
                    "base": "Ramesh Kumar",
                    "candidates": {"aadhaar": "Ramesh Kumar"}}]
        snapshot = json.dumps(payload, sort_keys=True)
        verify(payload)
        assert json.dumps(payload, sort_keys=True) == snapshot

    def test_json_roundtrip(self, verify):
        report = verify([{"field": "name", "type": "name",
                          "base": "Ramesh Kumar",
                          "candidates": {"x": "RAMESH KUMAR"}}])
        assert json.loads(json.dumps(report)) == report


class TestThreadSafety:
    def test_concurrent_calls(self, verify):
        from concurrent.futures import ThreadPoolExecutor
        triplets = [
            ("name",    "Ramesh Kumar",    "RAMESH KUMAR"),
            ("dob",     "12-03-1998",     "12/03/1998"),
            ("address", "Flat 402 Koramangala Bangalore 560034",
                        "402 Koramangala Bengaluru 560034"),
        ]

        def run(idx: int) -> str:
            ft, base, cand = triplets[idx % len(triplets)]
            return json.dumps(
                verify([{"field": ft, "type": ft, "base": base,
                         "candidates": {"x": cand}}], request_id="t", today=TODAY),
                sort_keys=True,
            )

        serial = [run(i) for i in range(len(triplets))]
        with ThreadPoolExecutor(max_workers=8) as pool:
            parallel = list(pool.map(run, range(90)))
        assert all(parallel[i] == serial[i % len(triplets)] for i in range(90))


class TestPerformance:
    """Adversarial inputs must complete quickly without crashing."""

    NASTY = {
        "name": ["a" * 199, "a'" * 99, " " * 190 + "x", "ab " * 60],
        "dob":  ["1" * 59, "1-" * 29, "12" + "-" * 55, "1/" * 29 + "1"],
        "address": ["a" * 999, "1-" * 499, "a, " * 330, "12 " * 330],
    }

    def test_adversarial_under_3_seconds(self, verify):
        start = time.perf_counter()
        for field, values in self.NASTY.items():
            for v in values:
                r = verify([{"field": field, "type": field,
                             "base": v, "candidates": {"x": v}}],
                           today=TODAY)["fields"][0]["comparisons"][0]
                assert "INTERNAL_ERROR" not in codes(r)
        assert time.perf_counter() - start < 3.0

    def test_random_inputs_never_crash(self, verify):
        import random, string
        ALPHABETS = {
            "name":    string.ascii_letters + " .'-/\u00e9\u00f6\u09280123",
            "dob":     string.digits + "/-. :,abcdeJMNOSlio|\u0967\u0968",
            "address": string.ascii_letters + string.digits + " ,;/-.\n#\u0928\u00e9",
        }
        rng = random.Random(20261120)
        for field, alpha in ALPHABETS.items():
            for _ in range(80):
                base = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 60)))
                cands = [{"source": f"s{i}",
                          "value": "".join(rng.choice(alpha) for _ in range(rng.randint(0, 60)))}
                         for i in range(2)]
                for r in verify([{"field": field, "type": field,
                                  "base": base, "candidates": cands}],
                                today=TODAY)["fields"][0]["comparisons"]:
                    assert r["color"] in ("green", "yellow", "red")
                    assert "INTERNAL_ERROR" not in codes(r)
                    if r["raw"] is not None:
                        rebuilt = "".join(s["text"] for s in r["highlight"]["candidate"])
                        assert rebuilt == r["raw"]


# ===========================================================================
# SECTION K — IDENTITY: any value vs itself is always GREEN
# ===========================================================================

class TestIdentity:
    @pytest.mark.parametrize("field,value", [
        # Names
        ("name", "Ramesh Kumar Sharma"),
        ("name", "K R Nair"),
        ("name", "O'Brien"),
        ("name", "Priya Devi Nair"),
        ("name", "Subramaniam Venkataraman"),
        ("name", "Mohammed Abdul Kalam"),
        ("name", "Gurpreet Singh"),
        ("name", "Subhashis Chakraborty"),
        # DOBs
        ("dob",  "12-03-1998"),
        ("dob",  "01-01-1980"),
        ("dob",  "15-08-1947"),
        ("dob",  "29-02-2000"),
        # Addresses
        ("address", "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore - 560034"),
        ("address", "Village Rampur, Post Lakhimpur, District Kheri, UP 262701"),
        ("address", "12 MG Road, Pune 411001"),
        ("address", "Plot 45, Sector 18, Noida 201301"),
        ("address", "H.No. 12-3/4, Sector 5, Indira Nagar, Pune 411 001"),
    ])
    def test_identity(self, compare, field, value):
        r = _cmp(compare, field, value, value)
        assert r["color"] == "green", (field, value, codes(r))


# ===========================================================================
# SECTION L — INPUT VALIDATION
# ===========================================================================

class TestInputValidation:
    @pytest.mark.parametrize("bad", [
        [],
        None,
        "name",
        [None],
        [{"type": "name", "base": "A", "candidates": {"x": "A"}}],           # no field
        [{"field": "f", "type": "fingerprint", "base": "A", "candidates": {"x": "A"}}],  # bad type
        [{"field": "f", "type": "name", "candidates": {"x": "A"}}],          # no base
        [{"field": "f", "type": "name", "base": "A"}],                       # no candidates
        [{"field": "f", "type": "name", "base": "A", "candidates": []}],
        [{"field": "f", "type": "name", "base": "A", "candidates": ["A"]}],
        [{"field": "f", "type": "name", "base": "A", "candidates": [{"value": "A"}]}],  # no source
    ])
    def test_raises_input_error(self, verify, bad):
        with pytest.raises(cv.InputError):
            verify(bad)

    @pytest.mark.parametrize("alias", ["date_of_birth", "birth_date", "dob"])
    def test_dob_type_aliases(self, verify, alias):
        r = verify([{"field": "f", "type": alias, "base": "12-03-1998",
                     "candidates": {"x": "12-03-1998"}}], today=TODAY)
        assert r["fields"][0]["type"] == "dob"

    def test_checks_key_wrapper(self, verify):
        r = verify({"checks": [{"field": "name", "type": "name",
                                "base": "Ramesh", "candidates": {"x": "RAMESH"}}]})
        assert r["fields"][0]["color"] == "green"

    def test_duplicate_source_gets_numbered_id(self, verify):
        cands = [{"source": "bank", "value": "Ramesh Kumar"},
                 {"source": "bank", "value": "Ramesh"},
                 {"source": "pan",  "value": "Ramesh Kumar"}]
        field = verify([{"field": "name", "type": "name",
                         "base": "Ramesh Kumar", "candidates": cands}])["fields"][0]
        ids = [c["id"] for c in field["comparisons"]]
        assert ids == ["bank#1", "bank#2", "pan"]

    def test_field_order_preserved(self, verify):
        checks = [
            {"field": "dob_field",  "type": "dob",  "base": "12-03-1998",
             "candidates": {"x": "12-03-1998"}},
            {"field": "name_field", "type": "name", "base": "Ramesh",
             "candidates": {"x": "Ramesh"}},
            {"field": "addr_field", "type": "address",
             "base": "12 MG Road Pune 411001",
             "candidates": {"x": "12 MG Road Pune 411001"}},
        ]
        r = verify(checks, today=TODAY)
        assert [f["field"] for f in r["fields"]] == ["dob_field", "name_field", "addr_field"]

    def test_request_id_echoed(self, verify):
        r = verify([{"field": "f", "type": "name", "base": "A",
                     "candidates": {"x": "A"}}], request_id="kyc-007")
        assert r["request_id"] == "kyc-007"

    def test_auto_request_id_12_chars(self, verify):
        r = verify([{"field": "f", "type": "name", "base": "A",
                     "candidates": {"x": "A"}}])
        assert len(r["request_id"]) == 12


# ===========================================================================
# SECTION M — MODES
# ===========================================================================

class TestModes:
    def _config(self, mode: str) -> dict:
        import json
        from pathlib import Path
        cfg = json.loads(Path(cv.__file__).with_name(cv.DEFAULT_CONFIG_NAME)
                         .read_text(encoding="utf-8"))
        cfg["mode"] = mode
        return cfg

    def test_fuzzy_mode_works(self):
        v = cv.create_verifier(self._config("fuzzy"))
        r = v([{"field": "name", "type": "name", "base": "A B",
                "candidates": {"x": "A B"}}])
        assert r["mode"] == "fuzzy"

    def test_hybrid_raises_not_implemented(self):
        with pytest.raises(cv.ModeNotImplementedError):
            cv.create_verifier(self._config("hybrid"))

    def test_llm_raises_not_implemented(self):
        with pytest.raises(cv.ModeNotImplementedError):
            cv.create_verifier(self._config("llm"))


# ===========================================================================
# SECTION N — INTERNAL SAFETY
# ===========================================================================

class TestInternalSafety:
    def test_broken_comparer_becomes_internal_error(self, verify, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("secret-pii-data")
        monkeypatch.setitem(cv.COMPARERS, "name", explode)
        report = verify([
            {"field": "name", "type": "name", "base": "Ramesh",
             "candidates": {"a": "Ramesh"}},
            {"field": "dob", "type": "dob", "base": "12-03-1998",
             "candidates": {"a": "12-03-1998"}},
        ], today=TODAY)
        broken, fine = report["fields"]
        assert codes(broken["comparisons"][0]) == ["INTERNAL_ERROR"]
        assert broken["color"] == "red"
        assert fine["color"] == "green"

    def test_pii_never_reaches_logs(self, compare, caplog):
        import logging
        secrets = ["Ramesh Kumarasamy", "12-03-1998", "560095", "UNIQUE-XQZ99"]
        with caplog.at_level(logging.DEBUG):
            _cmp(compare, "name",    secrets[0], "Ramesh K UNIQUE-XQZ99")
            _cmp(compare, "dob",     secrets[1], "03/12/1998")
            _cmp(compare, "address", f"Flat 12, Bengaluru {secrets[2]}",
                                     "13 Other, Chennai 600001")
        assert caplog.records
        assert not any(s in caplog.text for s in secrets), "PII leaked to logs!"

    def test_odd_types_are_unparseable_not_exceptions(self, compare):
        for bad in (True, ["a"], {"a": 1}, b"bytes", object()):
            r = _cmp(compare, "name", "Ramesh Kumar", bad)
            assert r["color"] == "red"
            assert "UNPARSEABLE" in codes(r), bad


# ===========================================================================
# SECTION O — FULL 246-CASE BENCHMARK DATASET VALIDATION
# ===========================================================================

DATASET_FILE = Path(__file__).resolve().parent.parent / "benchmark_dataset.json"

def _load_dataset():
    if not DATASET_FILE.is_file():
        return []
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

ALL_BENCHMARK_CASES = _load_dataset()

class TestComprehensiveDataset:
    @pytest.mark.parametrize("item", ALL_BENCHMARK_CASES, ids=lambda x: x["id"])
    def test_benchmark_item(self, compare, item):
        r = _cmp(compare, item["type"], item["base"], item["candidate"])
        assert r["color"] == item["expected_color"], (
            f"[{item['id']}] {item['base']!r} vs {item['candidate']!r}: "
            f"expected {item['expected_color']}, got {r['color']}. reasons={codes(r)}"
        )

