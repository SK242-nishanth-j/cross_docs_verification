"""
File: config.py
Purpose: Load, validate and prepare the cross_verify configuration.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .constants import DEFAULT_CONFIG_NAME
from .constants import ENV_CONFIG_PATH
from .constants import FLAG_OF_SEVERITY
from .constants import MODES
from .constants import REASONS
from .constants import Json
from .errors import ConfigError
from .text import fold

_REQUIRED = """
mode config_label limits.max_checks limits.max_candidates limits.max_text_length missing_placeholders
care_of_markers severity_overrides name.labels name.honorifics name.initials_only_min name.max_tokens
dob.labels dob.max_age address.labels address.label_words address.generic_words address.descriptor_words
address.abbreviations address.number_words address.cities address.fuzzy_min_length
address.edit_allowance address.text_min_coverage address.prefix_credit
address.pincode_near_prefix address.max_tokens
id.labels id.patterns id.lengths id.lookalikes id.mask_run_min id.min_visible_tail
amount.labels amount.default_currency amount.currencies amount.scales
amount.round_tolerance amount.near_percent
email.labels email.ignore_dots_domains email.ignore_tags
phone.labels phone.country_codes phone.default_country phone.national_length
phone.min_digits phone.min_visible_tail
text.abbreviations text.ignored_words text.vocabularies text.fuzzy_min_length
text.edit_allowance text.min_coverage text.max_tokens
""".split()  # noqa: SIM905


def _has(cfg: Json, path: str) -> bool:
    node: Any = cfg
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def check_config(cfg: Json) -> None:
    """Fail at start-up, with every problem listed, instead of in the middle of a request.

    Args:
        cfg: Raw configuration mapping.

    Raises:
        ConfigError: If a required key is missing or a value is invalid.
    """
    errors = [f"{path}: missing" for path in _REQUIRED if not _has(cfg, path)]
    if not errors:
        if cfg["mode"] not in MODES:
            errors.append(f"mode must be one of {', '.join(MODES)}")
        errors += [
            f"severity_overrides: bad entry {k}"
            for k, v in cfg["severity_overrides"].items()
            if k not in REASONS or v not in FLAG_OF_SEVERITY
        ]
    if errors:
        raise ConfigError("invalid configuration: " + "; ".join(errors))


def _phrase_regex(phrases: Sequence[str]) -> str:
    """Regex alternatives for phrases, longest first, spaces matching any whitespace."""
    return "|".join(
        re.escape(p).replace(r"\ ", r"\s+")
        for p in sorted(phrases, key=len, reverse=True)
    )


def load_config(path: str | os.PathLike[str] | None = None) -> Json:
    """Read the config file (argument, else $CROSS_VERIFY_CONFIG_PATH, else next to this file).

    Args:
        path: Optional path to the JSON configuration file.

    Returns:
        The validated configuration with its lookup tables.

    Raises:
        ConfigError: If the file is missing, unreadable or invalid.
    """
    target = Path(
        path
        or os.environ.get(ENV_CONFIG_PATH)
        or Path(__file__).with_name(DEFAULT_CONFIG_NAME)
    )
    try:
        cfg = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {target}") from exc
    except (OSError, ValueError) as exc:
        raise ConfigError(
            f"configuration file {target} is not readable JSON: {exc}"
        ) from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"configuration file {target} must hold a JSON object")
    return prepare_config(cfg)


def prepare_config(raw: Mapping[str, Any]) -> Json:
    """Validate a config mapping and add the lookup tables built from it (under '_rt').

    Args:
        raw: Configuration mapping (plain JSON values).

    Returns:
        A private copy with ``config_hash`` and the ``_rt`` lookup tables.

    Raises:
        ConfigError: If the configuration is invalid.
    """
    cfg: Json = json.loads(json.dumps(raw))  # private copy, plain JSON only
    check_config(cfg)
    cfg["config_hash"] = hashlib.sha256(
        json.dumps(cfg, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    name, addr = cfg["name"], cfg["address"]
    cities = {fold(city): fold(city) for city in addr["cities"]}
    for city, aliases in addr["cities"].items():
        cities.update({fold(alias): fold(city) for alias in aliases})
    cfg["_rt"] = {
        "placeholders": frozenset(fold(p) for p in cfg["missing_placeholders"]),
        "care_of": re.compile(
            rf"(?<![a-z0-9])(?:{_phrase_regex(cfg['care_of_markers'])})(?![a-z0-9])",
            re.IGNORECASE,
        ),
        "name_label": re.compile(
            rf"\s*(?:{_phrase_regex(name['labels'])})\s*[:\-\u2013]\s*", re.IGNORECASE
        ),
        "dob_label": re.compile(
            rf"(?<![a-z0-9])(?:{_phrase_regex(cfg['dob']['labels'])})(?![a-z0-9])\s*[:\-]?\s*",
            re.IGNORECASE,
        ),
        "address_label": re.compile(
            rf"\s*(?:{_phrase_regex(addr['labels'])})\s*[:\-\u2013]\s*", re.IGNORECASE
        ),
        "honorifics": {fold(h) for h in name["honorifics"]},
        "ignored_words": {fold(w) for w in addr["generic_words"] + addr["label_words"]},
        "descriptors": {fold(w) for w in addr["descriptor_words"]},
        "abbreviations": {fold(k): fold(v) for k, v in addr["abbreviations"].items()},
        "cities": cities,
        "max_city_words": max(len(c.split()) for c in cities),
        **_identity_tables(cfg),
    }
    return cfg


def _identity_tables(cfg: Json) -> Json:
    """The lookup tables of the id, amount, email, phone and text types."""
    idc, amount, email, phone, text = (
        cfg[k] for k in ("id", "amount", "email", "phone", "text")
    )
    currencies = {fold(symbol): code for symbol, code in amount["currencies"].items()}
    scales = {fold(word): float(factor) for word, factor in amount["scales"].items()}
    vocabularies = {
        kind: {
            fold(spelling): term
            for term, spellings in terms.items()
            for spelling in [term, *spellings]
        }
        for kind, terms in text["vocabularies"].items()
    }
    return {
        "id_label": re.compile(
            rf"\s*(?:{_phrase_regex(idc['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*",
            re.IGNORECASE,
        ),
        "id_patterns": {
            kind: re.compile(pattern) for kind, pattern in idc["patterns"].items()
        },
        "id_lookalikes": {
            str(k).upper(): str(v).upper() for k, v in idc["lookalikes"].items()
        },
        "id_mask_run": re.compile(rf"X{{{int(idc['mask_run_min'])},}}"),
        "amount_label": re.compile(
            rf"\s*(?:{_phrase_regex(amount['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*",
            re.IGNORECASE,
        ),
        "currency": re.compile(
            rf"(?<![a-z])(?:{_phrase_regex(list(amount['currencies']))})(?![a-z])",
            re.IGNORECASE,
        ),
        "currencies": currencies,
        "scale_after": re.compile(
            rf"[\s\-]*(?:{_phrase_regex(list(scales))})(?![a-z])", re.IGNORECASE
        ),
        "scales": scales,
        "email_label": re.compile(
            rf"\s*(?:{_phrase_regex(email['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*",
            re.IGNORECASE,
        ),
        "email_dot_domains": {fold(d) for d in email["ignore_dots_domains"]},
        "phone_label": re.compile(
            rf"\s*(?:{_phrase_regex(phone['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*",
            re.IGNORECASE,
        ),
        "text_abbreviations": {
            fold(k): fold(v) for k, v in text["abbreviations"].items()
        },
        "text_ignored": {fold(w) for w in text["ignored_words"]},
        "vocabularies": vocabularies,
    }
