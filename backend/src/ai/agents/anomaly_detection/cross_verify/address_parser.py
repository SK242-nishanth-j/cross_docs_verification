"""
File: address_parser.py
Purpose: Split a postal address into pincode, city, numbers and place words.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .constants import Json
from .constants import Span
from .text import add_reason
from .text import ascii_digits
from .text import failure
from .text import fold
from .text import has_foreign_letters

# An address is split into four parts that are compared one by one:
#   pincode | city | numbers (house number, "2nd cross" -> "cross:2") | place words
_PINCODE = re.compile(r"(?<!\d)([1-9]\d{2}) ?(\d{3})(?!\d)")


_ADDRESS_TOKEN = re.compile(r"[^\W_]+(?:[/\-][^\W_]+)*")


_SEGMENT = re.compile(r"[^,;\n\r|]+")


_HOUSE_NUMBER = re.compile(r"\d+[a-z]?(?:/\d+[a-z]?)*")


_ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)")


def _number_of(norm: str, number_words: Mapping[str, int]) -> str | None:
    """'5' -> '5', '2nd' -> '2', 'second' -> '2'. None when the word is not a number."""
    if norm.isdigit():
        return str(int(norm))
    ordinal = _ORDINAL.fullmatch(norm)
    if ordinal:
        return str(int(ordinal.group(1)))
    return str(number_words[norm]) if norm in number_words else None


def _address_tokens(
    text: str, regions: list[tuple[int, int]], skip: tuple[int, int] | None
) -> list[Json]:
    """Words of the address with their position. '12-3/4' stays whole, 'anna-nagar' is split."""
    tokens: list[Json] = []
    for start, end in regions:
        for m in _ADDRESS_TOKEN.finditer(text, start, end):
            if skip and m.start() < skip[1] and m.end() > skip[0]:
                continue  # the pincode
            piece = m.group()
            whole = fold(piece).replace("-", "/")
            if "/" not in whole or _HOUSE_NUMBER.fullmatch(whole):
                tokens.append({"norm": whole, "start": m.start(), "end": m.end()})
                continue
            for part in re.finditer(r"[^/\-]+", piece):
                tokens.append(
                    {
                        "norm": fold(part.group()),
                        "start": m.start() + part.start(),
                        "end": m.start() + part.end(),
                    }
                )
    return tokens


def parse_address(text: str, cfg: Json, side: str) -> Json:
    """Split an address into pincode, city, numbers and place words.

    Args:
        text: Raw address text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.

    Returns:
        The parsed address ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt, ac = cfg["_rt"], cfg["address"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    digits = ascii_digits(text)
    start = 0
    label = rt["address_label"].match(digits)
    if label:
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(
            reasons,
            cfg,
            "LABEL_STRIPPED",
            f"A label was removed from the {side} address.",
        )

    segments = [(m.start(), m.end()) for m in _SEGMENT.finditer(digits, start)]
    regions: list[tuple[int, int]] = []
    for a, b in segments:  # a line like "S/O Ramesh" is not part of the address
        care = rt["care_of"].match(
            digits, a + len(digits[a:b]) - len(digits[a:b].lstrip()), b
        )
        if care and len(segments) > 1:
            ignored.append((a, b, "ignored"))
            add_reason(
                reasons,
                cfg,
                "CARE_OF_REMOVED",
                f"The 'care of / son of' line was removed from the {side} address.",
            )
        elif care:
            ignored.append((care.start(), care.end(), "ignored"))
            regions.append((care.end(), b))
        else:
            regions.append((a, b))

    pincode, pin_span = None, None
    for m in _PINCODE.finditer(digits):  # the last 6-digit number in the text
        if any(a <= m.start() and m.end() <= b for a, b in regions):
            pincode, pin_span = m.group(1) + m.group(2), (m.start(), m.end())

    tokens = [t for t in _address_tokens(digits, regions, pin_span) if t["norm"]]
    foreign = [t for t in tokens if has_foreign_letters(t["norm"])]
    tokens = [t for t in tokens if t not in foreign]
    ignored += [(t["start"], t["end"], "ignored") for t in foreign]
    if len(tokens) > ac["max_tokens"]:
        return failure("TOO_LONG", f"The {side} address has too many words.")
    if foreign and not tokens and not pincode:
        return failure(
            "UNSUPPORTED_SCRIPT", f"The {side} address is not written in Latin letters."
        )
    if foreign:
        add_reason(
            reasons,
            cfg,
            "NON_LATIN_TEXT_IGNORED",
            f"Non-Latin text in the {side} address was ignored.",
        )
    for token in tokens:
        token["norm"] = rt["abbreviations"].get(token["norm"], token["norm"])

    city, city_spans = None, []
    for size in range(rt["max_city_words"], 0, -1):  # the last, longest known city name
        hit = next(
            (
                i
                for i in range(len(tokens) - size, -1, -1)
                if " ".join(t["norm"] for t in tokens[i : i + size]) in rt["cities"]
            ),
            None,
        )
        if hit is not None:
            city = rt["cities"][" ".join(t["norm"] for t in tokens[hit : hit + size])]
            city_spans = [(t["start"], t["end"]) for t in tokens[hit : hit + size]]
            del tokens[hit : hit + size]
            break

    numbers, words, used = [], [], set()
    for i, token in enumerate(
        tokens
    ):  # "2nd cross", "cross 2", "sector 5" become one item: "cross:2"
        if token["norm"] in rt["descriptors"]:
            for k in (i - 1, i + 1):
                value = (
                    _number_of(tokens[k]["norm"], ac["number_words"])
                    if 0 <= k < len(tokens) and k not in used
                    else None
                )
                if value:
                    near = tokens[k]
                    numbers.append(
                        {
                            "value": f"{token['norm']}:{value}",
                            "start": min(token["start"], near["start"]),
                            "end": max(token["end"], near["end"]),
                        }
                    )
                    used |= {i, k}
                    break
            used.add(i)
    for i, token in enumerate(tokens):
        norm = token["norm"]
        if i in used or norm in rt["ignored_words"]:
            continue
        ordinal = _ORDINAL.fullmatch(norm)
        if ordinal or _HOUSE_NUMBER.fullmatch(norm):
            if (
                sum(ch.isdigit() for ch in norm) <= 6
            ):  # longer digit strings are phone numbers and the like
                numbers.append(
                    {
                        "value": str(int(ordinal.group(1))) if ordinal else norm,
                        "start": token["start"],
                        "end": token["end"],
                    }
                )
        elif (
            len(norm) > 2 and norm.isalpha()
        ):  # one and two letter words ("KA", "MG") say too little
            stem = (
                norm[:-1]
                if len(norm) > 4 and norm.endswith("s") and not norm.endswith("ss")
                else norm
            )
            words.append(
                {
                    "norm": norm,
                    "key": stem,
                    "start": token["start"],
                    "end": token["end"],
                }
            )

    if not (pincode or city or numbers or words):
        return failure(
            "UNPARSEABLE", f"No address could be read from the {side} value."
        )
    parts = [
        " ".join(n["value"] for n in numbers),
        " ".join(w["norm"] for w in words),
        city or "",
        pincode or "",
    ]
    return {
        "ok": True,
        "raw": text,
        "pincode": pincode,
        "pin_span": pin_span,
        "city": city,
        "city_spans": city_spans,
        "numbers": numbers,
        "words": words,
        "ignored": ignored,
        "reasons": reasons,
        "normalized": ", ".join(p for p in parts if p),
    }
