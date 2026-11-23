from __future__ import annotations

import json
import logging
import os
import random
import string
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from conftest import TODAY, codes

import cross_verify as cv


def check(field_type: str, base: Any, candidates: Any, field: str = "f") -> dict[str, Any]:
    return {"field": field, "type": field_type, "base": base, "candidates": candidates}


# ---- the request ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        [],
        None,
        "name",
        [None],
        [{"type": "name", "base": "A", "candidates": {"x": "A"}}],  # no field
        [{"field": "f", "type": "fingerprint", "base": "A", "candidates": {"x": "A"}}],  # unknown type
        [{"field": "f", "type": "name", "candidates": {"x": "A"}}],  # no base
        [{"field": "f", "type": "name", "base": "A"}],  # no candidates
        [{"field": "f", "type": "name", "base": "A", "candidates": []}],
        [{"field": "f", "type": "name", "base": "A", "candidates": ["A"]}],
        [{"field": "f", "type": "name", "base": "A", "candidates": [{"value": "A"}]}],  # no source
    ],
)
def test_a_malformed_request_raises_input_error(verify, bad):  # type: ignore[no-untyped-def]
    with pytest.raises(cv.InputError):
        verify(bad)


def test_limits_come_from_the_config():
    config = json.loads(Path(cv.__file__).with_name(cv.DEFAULT_CONFIG_NAME).read_text(encoding="utf-8"))
    config["limits"].update(max_checks=1, max_candidates=2)
    verifier = cv.create_verifier(config)
    one = check("name", "A B", {"x": "A B"})
    with pytest.raises(cv.InputError, match="too many checks"):
        verifier([one, one])
    with pytest.raises(cv.InputError, match="too many candidates"):
        verifier([check("name", "A B", {"x": "A B", "y": "A B", "z": "A B"})])


def test_candidates_can_be_a_source_to_value_object_and_the_list_can_be_wrapped(verify):  # type: ignore[no-untyped-def]
    report = verify({"checks": [check("name", "Nishanth", {"aadhaar": "nishanth", "pan": "Nishanth J S"})]})
    assert {c["source"]: c["color"] for c in report["fields"][0]["comparisons"]} == {
        "aadhaar": "green",
        "pan": "yellow",
    }


def test_type_alias_and_input_order(verify):  # type: ignore[no-untyped-def]
    checks = [
        check("date_of_birth", "12-03-1998", {"z": "1998-03-12", "a": "1999"}, field="first"),
        check("name", "A B", {"x": "A B"}, field="second"),
    ]
    report = verify(checks, today=TODAY)
    assert [f["field"] for f in report["fields"]] == ["first", "second"]
    assert [(f["type"], c["source"]) for f in report["fields"][:1] for c in f["comparisons"]] == [
        ("dob", "z"),
        ("dob", "a"),
    ]


def test_a_source_used_twice_gets_distinct_ids(verify):  # type: ignore[no-untyped-def]
    candidates = [
        {"source": "bank", "value": "Nishanth"},
        {"source": "bank", "value": "Nishanth Kumar"},
        {"source": "pan", "value": "Nishanth"},
    ]
    comparisons = verify([check("name", "Nishanth", candidates)])["fields"][0]["comparisons"]
    assert [(c["id"], c["color"]) for c in comparisons] == [("bank#1", "green"), ("bank#2", "yellow"), ("pan", "green")]


# ---- the report -------------------------------------------------------------------------------


def test_the_worst_comparison_speaks_for_the_field_and_the_report(verify):  # type: ignore[no-untyped-def]
    report = verify(
        [
            check("name", "kumar sam", {"aadhaar": "KUMAR SAM", "pan": "sam kumar", "bank": "sam ramu"}),
            check("dob", "12-03-1998", {"a": "12/03/1998"}),
        ],
        today=TODAY,
    )
    name, dob = report["fields"]
    assert [c["color"] for c in name["comparisons"]] == ["green", "yellow", "red"]
    assert (name["color"], dob["color"]) == ("red", "green")
    assert report["overall"]["counts"] == {"match": 2, "warning": 1, "mismatch": 1}
    assert (report["overall"]["color"], report["overall"]["needs_review"]) == ("red", True)


def test_review_flags(verify):  # type: ignore[no-untyped-def]
    assert verify([check("name", "A Person", {"x": "a person"})])["overall"]["needs_review"] is False
    swapped = verify([check("name", "Kumar Sam", {"x": "Sam Kumar"})])
    result = swapped["fields"][0]["comparisons"][0]
    assert (result["color"], result["needs_review"]) == ("yellow", True)


def test_request_id_is_echoed_or_generated(verify):  # type: ignore[no-untyped-def]
    one = check("name", "A B", {"x": "A B"})
    assert verify([one], request_id="req-7")["request_id"] == "req-7"
    assert len(verify([one])["request_id"]) == 12


def test_missing_or_unreadable_base_makes_every_candidate_red(verify):  # type: ignore[no-untyped-def]
    report = verify([check("name", None, {"a": "Nishanth", "b": "Rahul"})])
    assert [codes(c) for c in report["fields"][0]["comparisons"]] == [["BASE_MISSING"], ["BASE_MISSING"]]
    broken = verify([check("dob", "not a date", {"a": "12-03-1998"})], today=TODAY)
    assert codes(broken["fields"][0]["comparisons"][0]) == ["UNPARSEABLE"]


def test_odd_value_types_are_red_not_errors(compare):  # type: ignore[no-untyped-def]
    for value in (True, ["a"], {"a": 1}, b"bytes", object()):
        assert codes(compare("name", "Nishanth", value)) == ["UNPARSEABLE"], value


def test_the_report_is_json_deterministic_and_leaves_the_request_alone(verify):  # type: ignore[no-untyped-def]
    payload = [
        check(
            "address",
            "Flat 402, Sai Residency, Koramangala, Bangalore 560034",
            [{"source": "a", "value": "402 Sai Residence Koramangala Bengaluru 560034"}],
        )
    ]
    snapshot = json.dumps(payload, sort_keys=True)
    first = verify(payload, request_id="r")
    assert first == verify(payload, request_id="r")
    assert json.loads(json.dumps(first)) == first
    assert json.dumps(payload, sort_keys=True) == snapshot


# ---- safety ---------------------------------------------------------------------------------------


def test_a_failing_comparison_is_contained_and_logged_without_values(monkeypatch, caplog, verify):  # type: ignore[no-untyped-def]
    def explode(*args: Any) -> Any:
        raise RuntimeError("secret-value-Nishanth")

    monkeypatch.setitem(cv.COMPARERS, "name", explode)
    with caplog.at_level(logging.DEBUG, logger="cross_verify"):
        report = verify(
            [check("name", "Nishanth", {"a": "Nishanth"}), check("dob", "12-03-1998", {"a": "12-03-1998"})], today=TODAY
        )
    broken, fine = report["fields"]
    assert (codes(broken["comparisons"][0]), broken["color"], fine["color"]) == (["INTERNAL_ERROR"], "red", "green")
    assert "RuntimeError" in caplog.text
    assert "secret-value" not in caplog.text


def test_values_never_reach_the_logs(compare, caplog):  # type: ignore[no-untyped-def]
    secrets = ["Nishanth Kumarasamy", "12-03-1998", "560034", "XQZ-unique"]
    with caplog.at_level(logging.DEBUG):
        compare("name", secrets[0], "Nishanth K XQZ-unique")
        compare("dob", secrets[1], "03/12/1998")
        compare("address", f"12 Test Road, Bengaluru {secrets[2]}", "13 Other Road, Chennai 600001")
    assert caplog.records
    assert not [s for s in secrets if s in caplog.text]


ALPHABETS = {
    "name": string.ascii_letters + " .'-/\u00e9\u00f6\u0928\u200b0123",
    "dob": string.digits + "/-. :,abcdeJMNOSlio|\u0967\u0968",
    "address": string.ascii_letters + string.digits + " ,;/-.\n#\u0928\u00e9",
}


@pytest.mark.parametrize("field_type", ["name", "dob", "address"])
def test_random_input_never_breaks_and_highlights_rebuild_the_text(verify, field_type):  # type: ignore[no-untyped-def]
    rng = random.Random(20261113)

    def text() -> str:
        return "".join(rng.choice(ALPHABETS[field_type]) for _ in range(rng.randint(0, 60)))

    for _ in range(300):
        base = text()
        candidates = [{"source": f"s{i}", "value": text()} for i in range(3)]
        for result in verify([check(field_type, base, candidates)], today=TODAY)["fields"][0]["comparisons"]:
            assert result["color"] in ("green", "yellow", "red")
            assert "INTERNAL_ERROR" not in codes(result)
            if result["raw"] is not None:
                assert "".join(s["text"] for s in result["highlight"]["candidate"]) == result["raw"]
            if result["highlight"]["base"]:
                assert "".join(s["text"] for s in result["highlight"]["base"]) == base


def test_a_value_equals_itself(compare):  # type: ignore[no-untyped-def]
    for field_type, value in [
        ("name", "J S Nishanth Kumar"),
        ("name", "O'Brien"),
        ("dob", "12-03-1998"),
        ("address", "Flat 402, Sai Residency, 2nd Cross, Koramangala, Bangalore - 560034"),
        ("address", "12 MG Road, Pune 411001"),
    ]:
        assert compare(field_type, value, value)["color"] == "green", value


def test_adversarial_input_finishes_quickly(verify):  # type: ignore[no-untyped-def]
    nasty = {
        "name": ["a" * 199, "a'" * 99, " " * 190 + "x", "ab " * 60, "'" * 199, "1" * 199],
        "dob": ["1" * 59, "1-" * 29, " " * 58 + "1", "a" * 59, "12" + "-" * 55, "1/" * 29 + "1"],
        "address": ["a" * 999, "1-" * 499, " " * 998 + "x", "a, " * 330, "1/" * 499, ", " * 499, "12 " * 330],
    }
    start = time.perf_counter()
    for field_type, values in nasty.items():
        for value in values:
            result = verify([check(field_type, value, {"x": value})], today=TODAY)["fields"][0]["comparisons"][0]
            assert "INTERNAL_ERROR" not in codes(result)
    assert time.perf_counter() - start < 2.0


def test_one_verifier_can_be_shared_between_threads(verify):  # type: ignore[no-untyped-def]
    pairs = [
        ("name", "kumar sam", "sam kumar"),
        ("dob", "12-03-1998", "03/12/1998"),
        ("address", "12 MG Road, Pune 411001", "12 M G Road Pune 411001"),
    ]

    def run(index: int) -> str:
        field_type, base, candidate = pairs[index % len(pairs)]
        return json.dumps(
            verify([check(field_type, base, {"x": candidate})], request_id="t", today=TODAY), sort_keys=True
        )

    serial = [run(i) for i in range(len(pairs))]
    with ThreadPoolExecutor(max_workers=8) as pool:
        parallel = list(pool.map(run, range(150)))
    assert all(parallel[i] == serial[i % len(pairs)] for i in range(150))


# ---- helpers and command line ---------------------------------------------------------------------


def test_text_helpers_keep_offsets_valid():
    assert cv.fold("José Müller") == "jose muller"
    text = "\u0967\u0968 Mar \u00c9"
    assert len(cv.ascii_digits(text)) == len(text)
    assert cv.ascii_digits("\u0967\u0968") == "12"


def test_read_env_file(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nA=1\nB = \"two words\"\nC='x'\nnot a pair\nD=a=b\n", encoding="utf-8")
    assert cv.read_env_file(env) == {"A": "1", "B": "two words", "C": "x", "D": "a=b"}


def test_cli_prints_the_report(tmp_path: Path, capsys, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "checks.json"
    source.write_text(json.dumps({"checks": [check("name", "kumar sam", {"pan": "sam kumar"})]}), encoding="utf-8")
    assert cv.main(["--input", str(source), "--compact"]) == 0
    assert json.loads(capsys.readouterr().out)["fields"][0]["comparisons"][0]["color"] == "yellow"


def test_cli_reports_errors_without_a_traceback(tmp_path: Path, capsys, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    for args in (
        ["--input", str(bad)],
        ["--input", str(tmp_path / "none.json")],
        ["--input", str(broken)],
        ["--input", str(bad), "--config", str(tmp_path / "none.json")],
    ):
        assert cv.main(args) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_loads_the_env_file(tmp_path: Path, capsys, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    os.environ.pop(cv.ENV_CONFIG_PATH, None)
    config = json.loads(Path(cv.__file__).with_name(cv.DEFAULT_CONFIG_NAME).read_text(encoding="utf-8"))
    config["severity_overrides"] = {"TOKEN_ORDER_DIFFERENT": "info"}  # the default file says yellow
    (tmp_path / "mine.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / ".env").write_text(f"{cv.ENV_CONFIG_PATH}=mine.json\n", encoding="utf-8")
    source = tmp_path / "checks.json"
    source.write_text(json.dumps([check("name", "kumar sam", {"pan": "sam kumar"})]), encoding="utf-8")
    try:
        assert cv.main(["--input", str(source), "--compact"]) == 0
    finally:
        os.environ.pop(cv.ENV_CONFIG_PATH, None)  # main() puts the .env values into the real environment
    assert json.loads(capsys.readouterr().out)["fields"][0]["comparisons"][0]["color"] == "green"
