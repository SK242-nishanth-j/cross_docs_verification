"""
File: identifiers.py
Purpose: Parse and compare identity numbers (Aadhaar, PAN, passport, voter ID, DL).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from rapidfuzz.distance import OSA

from .constants import Json
from .constants import Span
from .text import add_reason
from .text import ascii_digits
from .text import failure
from .text import make_outcome

# The number is cleaned to A-Z and 0-9, so spaces and dashes never matter. Three readings of the same number
# are warnings, never matches: a masked number, a look-alike character (O for 0) and a last-digits-only copy.


def _id_clean(text: str) -> str:
    """Keep only A-Z, 0-9 and the mask letter X. '2345 6789 1234' -> '234567891234'."""
    upper = ascii_digits(text).upper().replace("*", "X")
    return "".join(ch for ch in upper if ("A" <= ch <= "Z") or ch.isdigit())


def _id_shape(value: str, lookalikes: Mapping[str, str]) -> str:
    """Replace each character that is easily misread by one stand-in: 'ABCDEI234F' -> 'ABCDE1234F'."""
    return "".join(lookalikes.get(ch, ch) for ch in value)


def parse_id(text: str, cfg: Json, side: str, kind: str) -> Json:
    """Read an identity number. With a known kind, a value of the wrong shape is refused.

    Args:
        text: Raw number text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.
        kind: aadhaar, pan, passport, voter, driving_licence, or an empty string.

    Returns:
        The parsed number ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt = cfg["_rt"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start = 0
    label = rt["id_label"].match(text)
    if label and label.end() < len(text):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(
            reasons,
            cfg,
            "LABEL_STRIPPED",
            f"A label was removed from the {side} number.",
        )
    value = _id_clean(text[start:])
    if not value:
        return failure("UNPARSEABLE", f"No number could be read from the {side} value.")
    masked = bool(rt["id_mask_run"].search(value))
    pattern = rt["id_patterns"].get(kind)
    # "full" means the value has the shape of a whole number of this kind. A value that has not (a misread
    # character, only the last four digits, plain rubbish) is still compared, but can never come out green.
    full = masked or pattern is None or bool(pattern.fullmatch(value))
    return {
        "ok": True,
        "raw": text,
        "kind": kind,
        "value": value,
        "masked": masked,
        "full": full,
        "span": (start, len(text)),
        "ignored": ignored,
        "reasons": reasons,
        "normalized": value,
    }


def compare_ids(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two identity numbers. Green only when the whole number is the same.

    Args:
        base: Parsed base number.
        cand: Parsed candidate number.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons and highlight spans.
    """
    rt, tail = cfg["_rt"], cfg["id"]["min_visible_tail"]
    reasons = [*base["reasons"], *cand["reasons"]]
    b, c = base["value"], cand["value"]
    masked = base["masked"] or cand["masked"]
    whole = base["full"] and cand["full"]
    same = False
    if whole and b == c:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The numbers are the same.")
        same, kind = True, "match"
    elif b == c:
        add_reason(
            reasons,
            cfg,
            "ID_FORMAT_DOUBTFUL",
            f"The two values agree, but they are not shaped like a {base['kind'].replace('_', ' ')} number.",
        )
        kind = "spelling"
    elif (
        not masked
        and len(b) == len(c)
        and _id_shape(b, rt["id_lookalikes"]) == _id_shape(c, rt["id_lookalikes"])
    ):
        add_reason(
            reasons,
            cfg,
            "ID_OCR_VARIANT",
            "The numbers differ only in characters that look alike (O and 0, I and 1).",
        )
        kind = "spelling"
    elif masked or not whole:
        # A bureau prints XXXXXXXX1234, and some records hold only the last digits. Only the end can be
        # compared, so this is never green.
        visible_b, visible_c = (
            rt["id_mask_run"].split(b)[-1],
            rt["id_mask_run"].split(c)[-1],
        )
        shared = min(len(visible_b), len(visible_c))
        if shared >= tail and visible_b[-shared:] == visible_c[-shared:]:
            add_reason(
                reasons,
                cfg,
                "ID_MASKED" if masked else "ID_PARTIAL",
                f"One value holds only part of the number. The last {shared} characters agree.",
            )
            kind = "spelling"
        else:
            add_reason(
                reasons,
                cfg,
                "ID_DIFFERENT",
                "The part of the number that can be read does not agree.",
            )
            kind = "conflict"
    elif min(len(b), len(c)) >= tail and (b.endswith(c) or c.endswith(b)):
        add_reason(
            reasons,
            cfg,
            "ID_PARTIAL",
            "One number holds only the last characters of the other.",
        )
        kind = "spelling"
    else:
        add_reason(reasons, cfg, "ID_DIFFERENT", "The numbers are different.")
        if OSA.distance(b, c) == 1:
            add_reason(
                reasons,
                cfg,
                "POSSIBLE_TYPO",
                "The numbers differ in one character, which may be a typing error.",
            )
        kind = "conflict"
    out = make_outcome(reasons, same, base, cand)
    out["base_spans"].append((*base["span"], kind))
    out["cand_spans"].append((*cand["span"], kind))
    return out
