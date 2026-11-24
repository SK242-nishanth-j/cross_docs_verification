"""
File: addresses.py
Purpose: Addresses: compare the parts and explain the differences.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from .common import Json
from .common import add_reason
from .common import make_outcome
from .common import pair_up
from .common import word_relation


def _spans(items: Sequence[Json]) -> list[tuple[int, int]]:
    return [(item["start"], item["end"]) for item in items]


def _single_status(base_value: str | None, cand_value: str | None) -> str:
    """Compare one value (pincode, city): match, mismatch, or missing on one or both sides."""
    if base_value is None and cand_value is None:
        return "absent_both"
    if base_value is None or cand_value is None:
        return "absent_one"
    return "match" if base_value == cand_value else "mismatch"


def _compare_lists(
    b_keys: Sequence[str],
    c_keys: Sequence[str],
    relate: Any,
    min_coverage: float | None = None,
) -> Json:
    """Pair two lists of items and say how well they agree.

    status: match | partial (spelling or prefix) | subset (one side has extra items)
            | mismatch (both sides have items the other lacks) | absent_one | absent_both
    """
    pairs = pair_up(b_keys, c_keys, relate)
    left_b = [i for i in range(len(b_keys)) if i not in {p[0] for p in pairs}]
    left_c = [j for j in range(len(c_keys)) if j not in {p[1] for p in pairs}]
    coverage = (
        2 * sum(p[3] for p in pairs) / (len(b_keys) + len(c_keys))
        if b_keys or c_keys
        else 1.0
    )
    if not b_keys and not c_keys:
        status = "absent_both"
    elif not b_keys or not c_keys:
        status = "absent_one"
    elif left_b and left_c:
        status = (
            "partial"
            if min_coverage is not None and coverage >= min_coverage
            else "mismatch"
        )
    elif left_b or left_c:
        status = "subset"
    else:
        status = "match" if all(p[2] == "exact" for p in pairs) else "partial"
    return {"status": status, "pairs": pairs, "left_b": left_b, "left_c": left_c}


def _highlight_list(
    result: Json,
    b_spans: Sequence[tuple[int, int]],
    c_spans: Sequence[tuple[int, int]],
    out: Json,
) -> None:
    """Add highlight spans for a list component to the outcome."""
    for i, j, kind, _ in result["pairs"]:
        out["base_spans"].append(
            (*b_spans[i], "match" if kind == "exact" else "spelling")
        )
        out["cand_spans"].append(
            (*c_spans[j], "match" if kind == "exact" else "spelling")
        )
    conflict = result["status"] == "mismatch"
    out["base_spans"] += [
        (*b_spans[i], "conflict" if conflict else "missing") for i in result["left_b"]
    ]
    out["cand_spans"] += [
        (*c_spans[j], "conflict" if conflict else "extra") for j in result["left_c"]
    ]


# (part, status) -> (reason code, message). A part that matches needs no reason.
_ADDRESS_NOTES = {
    ("pincode", "near"): (
        "PINCODE_NEAR",
        "The pincodes differ in the last digits only.",
    ),
    ("pincode", "mismatch"): ("PINCODE_MISMATCH", "The pincodes differ."),
    ("city", "mismatch"): ("CITY_MISMATCH", "The cities differ."),
    ("number", "mismatch"): ("NUMBER_MISMATCH", "The house or street numbers differ."),
    ("number", "subset"): (
        "NUMBER_SUBSET",
        "One address has a house or street number the other lacks.",
    ),
    ("number", "partial"): (
        "NUMBER_SUBSET",
        "A house number matches only in its first part (12 and 12/3).",
    ),
    ("text", "mismatch"): (
        "WORDS_MISMATCH",
        "The place names in the two addresses do not match.",
    ),
    ("text", "subset"): (
        "INCOMPLETE_ADDRESS",
        "One address has place words the other lacks.",
    ),
    ("text", "partial"): (
        "WORDS_PARTIAL",
        "Some place words differ, but enough of them match.",
    ),
    ("text", "spelling"): (
        "SPELLING_VARIANT",
        "Some place words are spelled slightly differently.",
    ),
}
_ADDRESS_PARTS = {
    "pincode": "pincode",
    "city": "city",
    "number": "house or street numbers",
    "text": "place words",
}


def compare_addresses(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two parsed addresses part by part (pincode, city, numbers, place words).

    Args:
        base: Parsed base address.
        cand: Parsed candidate address.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons, highlight spans and a part-by-part table.
    """
    ac = cfg["address"]
    reasons = [*base["reasons"], *cand["reasons"]]

    def number_relation(a: str, b: str) -> tuple[str, float] | None:
        if a == b:
            return "exact", 1.0
        return (
            ("prefix", ac["prefix_credit"])
            if a.split("/", 1)[0] == b or b.split("/", 1)[0] == a
            else None
        )

    def word_rel(a: str, b: str) -> tuple[str, float] | None:
        return word_relation(a, b, ac["fuzzy_min_length"], ac["edit_allowance"])

    numbers = _compare_lists(
        [n["value"] for n in base["numbers"]],
        [n["value"] for n in cand["numbers"]],
        number_relation,
    )
    text = _compare_lists(
        [w["key"] for w in base["words"]],
        [w["key"] for w in cand["words"]],
        word_rel,
        ac["text_min_coverage"],
    )
    statuses = {
        "pincode": _single_status(base["pincode"], cand["pincode"]),
        "city": _single_status(base["city"], cand["city"]),
        "number": numbers["status"],
        "text": "spelling"
        if text["status"] == "partial" and not (text["left_b"] or text["left_c"])
        else text["status"],
    }
    n = ac["pincode_near_prefix"]
    if statuses["pincode"] == "mismatch" and base["pincode"][:n] == cand["pincode"][:n]:
        # one digit off is forgiven, but only when nothing else disagrees
        others = [s for part, s in statuses.items() if part != "pincode"]
        statuses["pincode"] = "mismatch" if "mismatch" in others else "near"

    # ---- reasons ----
    for part, status in statuses.items():
        if (part, status) in _ADDRESS_NOTES:
            add_reason(reasons, cfg, *_ADDRESS_NOTES[part, status])
    present = {
        "pincode": base["pincode"],
        "city": base["city"],
        "number": base["numbers"],
        "text": base["words"],
    }
    one_sided = [p for p, s in statuses.items() if s == "absent_one"]
    for side, lacking in (
        ("candidate", [p for p in one_sided if present[p]]),
        ("base", [p for p in one_sided if not present[p]]),
    ):
        if lacking:
            add_reason(
                reasons,
                cfg,
                "INCOMPLETE_ADDRESS",
                f"The {side} lacks the {', '.join(_ADDRESS_PARTS[p] for p in lacking)}.",
            )
    if not (
        statuses["pincode"] == "match"
        or any(pair[2] == "exact" for pair in numbers["pairs"])
    ):
        add_reason(
            reasons,
            cfg,
            "NO_ANCHOR_MATCH",
            "Neither the pincode nor a house number matches.",
        )
    exact = all(s in ("match", "absent_both") for s in statuses.values())
    if exact:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The addresses are the same.")

    out = make_outcome(reasons, exact, base, cand)

    # ---- highlights, and a part-by-part table for the UI ----
    kinds = {"match": "match", "near": "spelling", "mismatch": "conflict"}
    pin_spans = (
        [base["pin_span"]] if base["pin_span"] else [],
        [cand["pin_span"]] if cand["pin_span"] else [],
    )
    for part, (b_spans, c_spans) in (
        ("pincode", pin_spans),
        ("city", (base["city_spans"], cand["city_spans"])),
    ):
        out["base_spans"] += [
            (*s, kinds.get(statuses[part], "missing")) for s in b_spans
        ]
        out["cand_spans"] += [(*s, kinds.get(statuses[part], "extra")) for s in c_spans]
    _highlight_list(numbers, _spans(base["numbers"]), _spans(cand["numbers"]), out)
    _highlight_list(text, _spans(base["words"]), _spans(cand["words"]), out)
    values = {
        "pincode": (base["pincode"], cand["pincode"]),
        "city": (base["city"], cand["city"]),
        "number": (
            [n["value"] for n in base["numbers"]],
            [n["value"] for n in cand["numbers"]],
        ),
        "text": (
            [w["norm"] for w in base["words"]],
            [w["norm"] for w in cand["words"]],
        ),
    }
    out["components"] = [
        {"component": p, "status": statuses[p], "base": b, "candidate": c}
        for p, (b, c) in values.items()
    ]
    return out
