"""
File: common.py
Purpose: Shared types, reason codes and the text normalisation every field type uses.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from rapidfuzz.distance import OSA

Json = dict[str, Any]
Span = tuple[int, int, str]  # (start, end, kind) over the raw text, used for highlights


REASONS: dict[
    str, str
] = {  # reason code -> severity. The colour is the worst severity of the reasons found.
    "EXACT": "info",
    "NORMALIZED_EQUAL": "info",
    "HONORIFIC_IGNORED": "info",
    "CARE_OF_REMOVED": "info",
    "LABEL_STRIPPED": "info",
    "POSSIBLE_TYPO": "info",
    "TOKEN_ORDER_DIFFERENT": "warn",
    "INITIAL_EXPANDED": "warn",
    "EXTRA_INITIALS": "warn",
    "MISSING_INITIALS": "warn",
    "EXTRA_TOKEN": "warn",
    "MISSING_TOKEN": "warn",
    "SPACING_DIFFERENCE": "warn",
    "SPELLING_VARIANT": "warn",
    "NON_LATIN_TEXT_IGNORED": "warn",
    "INCOMPLETE_ADDRESS": "warn",
    "NUMBER_SUBSET": "warn",
    "PINCODE_NEAR": "warn",
    "WORDS_PARTIAL": "warn",
    "ID_MASKED": "warn",
    "ID_OCR_VARIANT": "warn",
    "ID_PARTIAL": "warn",
    "ID_FORMAT_DOUBTFUL": "warn",
    "PHONE_COUNTRY_ASSUMED": "warn",
    "AMOUNT_ROUNDED": "warn",
    "AMOUNT_NEAR": "warn",
    "CURRENCY_ASSUMED": "warn",
    "EMAIL_ALIAS": "warn",
    "PHONE_PARTIAL": "warn",
    "DIFFERENCE_UNCLASSIFIED": "warn",
    "MISSING_VALUE": "fail",
    "BASE_MISSING": "fail",
    "UNPARSEABLE": "fail",
    "UNSUPPORTED_SCRIPT": "fail",
    "TOO_LONG": "fail",
    "DATE_IMPLAUSIBLE": "fail",
    "INTERNAL_ERROR": "fail",
    "TOKEN_CONFLICT": "fail",
    "INSUFFICIENT_NAME": "fail",
    "NO_ANCHOR_MATCH": "fail",
    "DATE_DIFFERENT": "fail",
    "PINCODE_MISMATCH": "fail",
    "CITY_MISMATCH": "fail",
    "NUMBER_MISMATCH": "fail",
    "WORDS_MISMATCH": "fail",
    "ID_DIFFERENT": "fail",
    "AMOUNT_DIFFERENT": "fail",
    "CURRENCY_MISMATCH": "fail",
    "EMAIL_DIFFERENT": "fail",
    "PHONE_DIFFERENT": "fail",
    "TEXT_DIFFERENT": "fail",
}
FLAG_OF_SEVERITY = {"info": "green", "warn": "yellow", "fail": "red"}
FLAG_RANK = {"green": 0, "yellow": 1, "red": 2}
STATUS_OF_FLAG = {"green": "match", "yellow": "warning", "red": "mismatch"}
MODES = ("fuzzy", "hybrid", "llm")
FIELD_TYPES = ("name", "dob", "address", "id", "amount", "email", "phone", "text")

# "type" values a caller may use. Each one names the field type and, where it is implied, the kind.
TYPE_ALIASES: dict[str, tuple[str, str]] = {
    "date_of_birth": ("dob", ""),
    "birth_date": ("dob", ""),
    "aadhaar": ("id", "aadhaar"),
    "aadhar": ("id", "aadhaar"),
    "aadhaar_number": ("id", "aadhaar"),
    "pan": ("id", "pan"),
    "pan_number": ("id", "pan"),
    "passport": ("id", "passport"),
    "passport_number": ("id", "passport"),
    "voter_id": ("id", "voter"),
    "driving_licence": ("id", "driving_licence"),
    "driving_license": ("id", "driving_licence"),
    "id_number": ("id", ""),
    "document_number": ("id", ""),
    "money": ("amount", ""),
    "fee": ("amount", ""),
    "email_id": ("email", ""),
    "e_mail": ("email", ""),
    "mobile": ("phone", ""),
    "mobile_number": ("phone", ""),
    "phone_number": ("phone", ""),
    "gender": ("text", "gender"),
    "sex": ("text", "gender"),
    "relationship": ("text", "relationship"),
    "relation": ("text", "relationship"),
    "nationality": ("text", "nationality"),
    "organisation": ("text", ""),
    "organization": ("text", ""),
    "university": ("text", ""),
    "employer": ("text", ""),
    "course": ("text", ""),
}
ENV_CONFIG_PATH = "CROSS_VERIFY_CONFIG_PATH"
DEFAULT_CONFIG_NAME = "cross_verify_config.json"


def add_reason(reasons: list[Json], cfg: Json, code: str, message: str) -> None:
    """Append a reason once. The config can change its severity (severity_overrides).

    Args:
        reasons: The reason list to extend.
        cfg: Prepared configuration.
        code: Reason code (a key of REASONS).
        message: Human-readable explanation without personal data.
    """
    if any(r["code"] == code for r in reasons):
        return
    severity = cfg["severity_overrides"].get(code, REASONS[code])
    reasons.append({"code": code, "severity": severity, "message": message})


_WORD = re.compile(
    r"(?:[^\W_]|[\u0300-\u036f])+(?:['\u2019](?:[^\W_]|[\u0300-\u036f])+)*"
)  # letters and digits


def fold(text: str) -> str:
    """Lower-case and drop accents and invisible characters: 'José' -> 'jose'.

    Args:
        text: Any text.

    Returns:
        The folded text.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        ch
        for ch in decomposed
        if not unicodedata.combining(ch)
        and unicodedata.category(ch) not in ("Cf", "Cc")
    )


def has_foreign_letters(text: str) -> bool:
    """True for letters outside the Latin script (Devanagari, Tamil, ...). Not supported yet.

    Args:
        text: Any text.

    Returns:
        Whether the text has a non-Latin letter.
    """
    return any(ch.isalpha() and ord(ch) > 0x24F for ch in text)


def ascii_digits(text: str) -> str:
    """Turn Devanagari, Tamil, full-width ... digits into 0-9, keeping the length.

    Args:
        text: Any text.

    Returns:
        The text with ASCII digits.
    """
    return "".join(
        str(unicodedata.decimal(ch)) if unicodedata.category(ch) == "Nd" else ch
        for ch in text
    )


def is_missing(value: Any, cfg: Json) -> bool:
    """Tell whether a value is absent: None, empty, or a placeholder such as "N/A".

    Args:
        value: The raw value.
        cfg: Prepared configuration (holds the placeholders).

    Returns:
        True when the value counts as missing.
    """
    if value is None:
        return True
    return isinstance(value, str) and fold(value).strip() in cfg["_rt"][
        "placeholders"
    ] | {""}


def show(value: Any) -> str | None:
    """The text shown as 'raw'. None when the value is not text, a number or a date.

    Args:
        value: The raw value.

    Returns:
        The display text, or None.
    """
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date | str):
        return value if isinstance(value, str) else value.isoformat()
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)
    return None


def build_segments(raw: str, spans: Sequence[Span]) -> list[Json]:
    """Cut the raw text into pieces for highlighting. Joining the pieces gives back the raw text.

    Args:
        raw: The raw text.
        spans: (start, end, kind) ranges to highlight.

    Returns:
        Ordered segments with text, start, end and kind.
    """
    out: list[Json] = []
    pos = 0
    for start, end, kind in sorted(s for s in spans if 0 <= s[0] < s[1] <= len(raw)):
        if start < pos:
            continue
        if start > pos:
            out.append(_piece(raw, pos, start, None))
        out.append(_piece(raw, start, end, kind))
        pos = end
    if pos < len(raw):
        out.append(_piece(raw, pos, len(raw), None))
    return out


def _piece(raw: str, start: int, end: int, kind: str | None) -> Json:
    text = raw[start:end]
    return {
        "text": text,
        "start": start,
        "end": end,
        "kind": kind or ("text" if text.strip() else "space"),
    }


def word_relation(
    a: str, b: str, min_length: int, table: Sequence[Sequence[int]]
) -> tuple[str, float] | None:
    """How two folded words relate. Used for address words.

    Args:
        a: First folded word.
        b: Second folded word.
        min_length: Shortest word length allowed a spelling difference.
        table: (minimum length, allowed edits) pairs.

    Returns:
        ("exact" | "spelling", similarity), or None when unrelated.
    """
    if a == b:
        return "exact", 1.0
    longest = max(len(a), len(b))
    allowed = max((edits for min_len, edits in table if longest >= min_len), default=0)
    distance = OSA.distance(a, b)
    if min(len(a), len(b)) >= min_length and 0 < distance <= allowed:
        return "spelling", 1.0 - distance / longest
    return None


def pair_up(
    left: Sequence[str], right: Sequence[str], relate: Any
) -> list[tuple[int, int, str, float]]:
    """One-to-one pairing of two word lists: best similarity first, nearest position as tie-break.

    Args:
        left: First word list.
        right: Second word list.
        relate: Function returning (kind, similarity) or None for two words.

    Returns:
        (left index, right index, kind, similarity) tuples, sorted.
    """
    options = []
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            found = relate(a, b)
            if found:
                options.append((-found[1], abs(i - j), i, j, found[0]))
    pairs, used_left, used_right = [], set(), set()
    for neg_sim, _, i, j, kind in sorted(options):
        if i not in used_left and j not in used_right:
            used_left.add(i)
            used_right.add(j)
            pairs.append((i, j, kind, -neg_sim))
    return sorted(pairs)


def make_outcome(
    reasons: list[Json], exact: bool, base: Json, cand: Json, **extra: Any
) -> Json:
    """What every compare_* function returns.

    Args:
        reasons: Reasons found.
        exact: Whether the values are provably equal.
        base: Parsed base value.
        cand: Parsed candidate value.
        **extra: Additional outcome keys (for example components).

    Returns:
        The outcome mapping.
    """
    return {
        "reasons": reasons,
        "exact": exact,
        "base_normalized": base["normalized"],
        "candidate_normalized": cand["normalized"],
        "base_spans": [*base["ignored"]],
        "cand_spans": [*cand["ignored"]],
        **extra,
    }


def failure(code: str, message: str) -> Json:
    """A value that could not be parsed. parse_* return this.

    Args:
        code: Reason code.
        message: Human-readable explanation without personal data.

    Returns:
        ``{"ok": False, "code": code, "message": message}``.
    """
    return {"ok": False, "code": code, "message": message}
