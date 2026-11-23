from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import cross_verify as cv

CONFIG_FILE = Path(cv.__file__).with_name(cv.DEFAULT_CONFIG_NAME)


def raw_config() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return data


def run_one(verifier: Any, base: str, candidate: str) -> dict[str, Any]:
    check = {"field": "f", "type": "name", "base": base, "candidates": [{"source": "doc", "value": candidate}]}
    result: dict[str, Any] = verifier([check])["fields"][0]["comparisons"][0]
    return result


def test_default_config_loads_and_has_a_stable_hash():
    first, second = cv.load_config(), cv.load_config()
    assert first["config_hash"] == second["config_hash"]
    assert len(first["config_hash"]) == 12
    changed = raw_config()
    changed["name"]["max_tokens"] = 11
    assert cv.prepare_config(changed)["config_hash"] != first["config_hash"]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda c: c.pop("severity_overrides"), "severity_overrides: missing"),
        (lambda c: c["name"].pop("honorifics"), "name.honorifics: missing"),
        (lambda c: c.update(mode="turbo"), "mode must be one of"),
        (lambda c: c["severity_overrides"].update(NOT_A_CODE="warn"), "bad entry NOT_A_CODE"),
        (lambda c: c["severity_overrides"].update(EXTRA_TOKEN="loud"), "bad entry EXTRA_TOKEN"),
        (lambda c: c["severity_overrides"].update(LOW_SCORE="fail"), "bad entry LOW_SCORE"),  # the code was removed
    ],
)
def test_a_bad_configuration_stops_start_up_with_a_clear_message(edit, message):  # type: ignore[no-untyped-def]
    broken = raw_config()
    edit(broken)
    with pytest.raises(cv.ConfigError, match=message):
        cv.prepare_config(broken)


def test_all_missing_settings_are_listed_together():
    broken = raw_config()
    broken.pop("limits")
    broken.pop("dob")
    with pytest.raises(cv.ConfigError) as info:
        cv.prepare_config(broken)
    assert "limits.max_checks: missing" in str(info.value)
    assert "dob.max_age: missing" in str(info.value)


def test_config_must_be_plain_json_and_is_copied():
    broken = raw_config()
    broken["config_label"] = object()
    with pytest.raises(TypeError):
        cv.prepare_config(broken)
    source = raw_config()
    verifier = cv.create_verifier(source)
    source["name"]["honorifics"].clear()  # changing the input later has no effect
    assert run_one(verifier, "Nishanth", "Mr Nishanth")["color"] == "green"


@pytest.mark.parametrize("mode", ["hybrid", "llm"])
def test_reserved_modes_are_refused_and_never_replaced_by_fuzzy(mode):  # type: ignore[no-untyped-def]
    config = raw_config()
    config["mode"] = mode
    with pytest.raises(cv.ModeNotImplementedError, match=f"mode '{mode}' is not developed yet"):
        cv.create_verifier(config)
    with pytest.raises(NotImplementedError):
        cv.create_verifier(config)


def test_the_report_names_the_mode_and_config(verify):  # type: ignore[no-untyped-def]
    report = verify([{"field": "n", "type": "name", "base": "A B", "candidates": {"x": "A B"}}])
    assert report["mode"] == "fuzzy"
    assert "engine_version" not in report
    assert report["config_hash"] == cv.load_config()["config_hash"]


def test_config_path_comes_from_the_argument_then_the_environment_then_the_default(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    tuned = raw_config()
    tuned["severity_overrides"] = {"TOKEN_ORDER_DIFFERENT": "info"}
    from_env = tmp_path / "env.json"
    from_env.write_text(json.dumps(tuned), encoding="utf-8")
    monkeypatch.delenv(cv.ENV_CONFIG_PATH, raising=False)
    assert run_one(cv.create_verifier(), "kumar sam", "sam kumar")["color"] == "yellow"  # default file
    monkeypatch.setenv(cv.ENV_CONFIG_PATH, str(from_env))
    assert run_one(cv.create_verifier(), "kumar sam", "sam kumar")["color"] == "green"  # environment
    assert run_one(cv.create_verifier(config_path=CONFIG_FILE), "kumar sam", "sam kumar")["color"] == "yellow"  # argument


def test_bad_files_are_config_errors(tmp_path):  # type: ignore[no-untyped-def]
    with pytest.raises(cv.ConfigError, match="not found"):
        cv.load_config(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(cv.ConfigError, match="not readable JSON"):
        cv.load_config(broken)
    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(cv.ConfigError, match="JSON object"):
        cv.load_config(listing)


def test_a_severity_override_changes_the_colour():
    lenient = raw_config()
    lenient["severity_overrides"] = {"EXTRA_INITIALS": "info"}
    result = run_one(cv.create_verifier(lenient), "Nishanth", "Nishanth J S")
    assert result["color"] == "green"
    strict = raw_config()
    strict["severity_overrides"] = {"EXTRA_INITIALS": "fail"}
    assert run_one(cv.create_verifier(strict), "Nishanth", "Nishanth J S")["color"] == "red"


def test_thresholds_come_from_the_config():
    assert run_one(cv.create_verifier(), "Nishanth", "N")["color"] == "red"  # one initial says too little
    config = raw_config()
    config["name"]["initials_only_min"] = 1
    assert run_one(cv.create_verifier(config), "Nishanth", "N")["color"] == "yellow"
