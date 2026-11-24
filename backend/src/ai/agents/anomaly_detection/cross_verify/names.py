"""
File: names.py
Purpose: Names: parse, match word by word (initials, order, spelling), explain.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: rapidfuzz
"""

from __future__ import annotations

import datetime as dt

from .common import _WORD
from .common import Json
from .common import Span
from .common import add_reason
from .common import failure
from .common import fold
from .common import has_foreign_letters
from .common import make_outcome
from .common import pair_up

_VOWELS = set("aeiou")


def parse_name(raw: str, cfg: Json, side: str) -> Json:
    """Split a name into folded words with their position in the raw text.

    Args:
        raw: Raw name text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.

    Returns:
        The parsed name ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt, nc = cfg["_rt"], cfg["name"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start, end = 0, len(raw)
    label = rt["name_label"].match(raw)
    if label:
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(
            reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} name."
        )
    care = rt["care_of"].search(raw, start)
    if care:  # "Nishanth S/O Ramesh": keep only the name before it
        ignored.append((care.start(), len(raw), "ignored"))
        end = care.start()
        add_reason(
            reasons,
            cfg,
            "CARE_OF_REMOVED",
            f"The 'son of / wife of' part was removed from the {side} name.",
        )

    words: list[Json] = []
    foreign = False
    for match in _WORD.finditer(raw, start, end):
        if has_foreign_letters(match.group()):
            foreign = True
            ignored.append((match.start(), match.end(), "ignored"))
            continue
        norm = "".join(
            ch for ch in fold(match.group()) if ch.isalpha()
        )  # digits inside a word are OCR noise
        if norm:
            words.append({"norm": norm, "start": match.start(), "end": match.end()})

    while len(words) > 1:  # leading titles: Mr, Dr, Shri ... (never the only word)
        if words[0]["norm"] in rt["honorifics"]:
            ignored.append((words[0]["start"], words[0]["end"], "ignored"))
            add_reason(
                reasons,
                cfg,
                "HONORIFIC_IGNORED",
                f"A title was ignored in the {side} name.",
            )
            words.pop(0)
        else:
            break

    tokens: list[Json] = []
    for word in words:  # "JS" (short, no vowel) means the initials J and S
        norm = word["norm"]
        if (
            2 <= len(norm) <= 3
            and norm.isascii()
            and not _VOWELS & set(norm)
            and word["end"] - word["start"] == len(norm)
        ):
            tokens += [
                {"norm": ch, "start": word["start"] + k, "end": word["start"] + k + 1}
                for k, ch in enumerate(norm)
            ]
        else:
            tokens.append(word)

    if foreign and not tokens:
        return failure(
            "UNSUPPORTED_SCRIPT", f"The {side} name is not written in Latin letters."
        )
    if not tokens:
        return failure("UNPARSEABLE", f"No name could be read from the {side} value.")
    if len(tokens) > nc["max_tokens"]:
        return failure("TOO_LONG", f"The {side} name has too many words.")
    if foreign:
        add_reason(
            reasons,
            cfg,
            "NON_LATIN_TEXT_IGNORED",
            f"Non-Latin text in the {side} name was ignored.",
        )
    return {
        "ok": True,
        "raw": raw,
        "tokens": tokens,
        "ignored": ignored,
        "reasons": reasons,
        "normalized": " ".join(t["norm"] for t in tokens),
    }


def _is_initial(token: Json) -> bool:
    return len(token["norm"]) == 1


def _join_neighbours(mine: list[Json], other: list[Json]) -> list[Json]:
    """'Nishanth Kumar' vs 'Nishanthkumar': join two words when the other name has them as one word."""
    words = {t["norm"] for t in other}
    out: list[Json] = []
    i = 0
    while i < len(mine):
        a, b = mine[i], mine[i + 1] if i + 1 < len(mine) else None
        if (
            b
            and a["norm"] + b["norm"] in words
            and a["norm"] not in words
            and b["norm"] not in words
        ):
            out.append(
                {
                    "norm": a["norm"] + b["norm"],
                    "start": a["start"],
                    "end": b["end"],
                    "joined": True,
                }
            )
            i += 2
        else:
            out.append(a)
            i += 1
    return out


def _match_initials(
    b: list[Json], c: list[Json], used_b: set[int], used_c: set[int]
) -> list[tuple[int, int, str]]:
    """Pair initials: the same letter on both sides, or an initial standing for a leftover word."""
    pairs: list[tuple[int, int, str]] = []

    def take(i: int, j: int, kind: str) -> None:
        pairs.append((i, j, kind))
        used_b.add(i)
        used_c.add(j)

    for i in range(len(b)):
        for j in range(len(c)):
            if (
                i not in used_b
                and j not in used_c
                and _is_initial(b[i])
                and b[i]["norm"] == c[j]["norm"]
            ):
                take(i, j, "initial_exact")
    for i in range(len(b)):  # base initial -> candidate word starting with it
        if i not in used_b and _is_initial(b[i]):
            for j in range(len(c)):
                if (
                    j not in used_c
                    and not _is_initial(c[j])
                    and c[j]["norm"].startswith(b[i]["norm"])
                ):
                    take(i, j, "initial_expanded")
                    break
    for j in range(len(c)):  # candidate initial -> base word starting with it
        if j not in used_c and _is_initial(c[j]):
            for i in range(len(b)):
                if (
                    i not in used_b
                    and not _is_initial(b[i])
                    and b[i]["norm"].startswith(c[j]["norm"])
                ):
                    take(i, j, "initial_expanded")
                    break
    return pairs


def _crossing(pairs: list[tuple[int, int]]) -> set[int]:
    """Base positions of pairs whose order differs between the two names."""
    return {
        i
        for i, j in pairs
        for i2, j2 in pairs
        if (i < i2 and j > j2) or (i > i2 and j < j2)
    }


def _name_reasons(
    reasons: list[Json], m: Json, b: list[Json], c: list[Json], cfg: Json
) -> None:
    """Turn the pairing result into reasons."""
    if m["moved"]:
        add_reason(
            reasons,
            cfg,
            "TOKEN_ORDER_DIFFERENT",
            "The same name parts appear in a different order.",
        )
    if any(kind == "initial_expanded" for _, _, kind in m["initials"]):
        add_reason(
            reasons, cfg, "INITIAL_EXPANDED", "An initial stands for a full word."
        )

    words_b = [b[i]["norm"] for i in m["left_b"] if not _is_initial(b[i])]
    words_c = [c[j]["norm"] for j in m["left_c"] if not _is_initial(c[j])]
    if (
        m["left_b"] and m["left_c"]
    ):  # each side has something the other lacks: a word was replaced
        left_b = ", ".join(b[i]["norm"] for i in m["left_b"])
        left_c = ", ".join(c[j]["norm"] for j in m["left_c"])
        add_reason(
            reasons,
            cfg,
            "TOKEN_CONFLICT",
            f"'{left_c}' in the candidate does not match '{left_b}' in the base.",
        )
        return
    if words_b:
        add_reason(
            reasons, cfg, "MISSING_TOKEN", f"The candidate lacks {', '.join(words_b)}."
        )
    if words_c:
        add_reason(
            reasons,
            cfg,
            "EXTRA_TOKEN",
            f"The candidate has the extra {', '.join(words_c)}.",
        )
    if len(m["left_b"]) > len(words_b):
        add_reason(
            reasons, cfg, "MISSING_INITIALS", "The candidate lacks some initials."
        )
    if len(m["left_c"]) > len(words_c):
        add_reason(reasons, cfg, "EXTRA_INITIALS", "The candidate has extra initials.")
    if not m["words"] and len(m["initials"]) < cfg["name"]["initials_only_min"]:
        add_reason(
            reasons,
            cfg,
            "INSUFFICIENT_NAME",
            "Too little of the name is present to confirm a match.",
        )


def compare_names(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two parsed names.

    Args:
        base: Parsed base name.
        cand: Parsed candidate name.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons and highlight spans.
    """
    b, c = base["tokens"], cand["tokens"]
    reasons = [*base["reasons"], *cand["reasons"]]
    if [t["norm"] for t in b] == [t["norm"] for t in c]:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The names are the same.")
        out = make_outcome(reasons, True, base, cand)
        out["base_spans"] += [(t["start"], t["end"], "match") for t in b]
        out["cand_spans"] += [(t["start"], t["end"], "match") for t in c]
        return out

    b, c = _join_neighbours(b, c), _join_neighbours(c, b)
    if any(t.get("joined") for t in (*b, *c)):
        add_reason(
            reasons,
            cfg,
            "SPACING_DIFFERENCE",
            "A name is written as one word on one side and two on the other.",
        )

    def relate(x: str, y: str) -> tuple[str, float] | None:
        return (
            ("exact", 1.0) if x == y else None
        )  # a name is compared letter for letter: Vinay and Vijay differ

    full_b = [i for i, t in enumerate(b) if not _is_initial(t)]
    full_c = [j for j, t in enumerate(c) if not _is_initial(t)]
    found = pair_up(
        [b[i]["norm"] for i in full_b], [c[j]["norm"] for j in full_c], relate
    )
    words = [(full_b[i], full_c[j], kind, sim) for i, j, kind, sim in found]
    used_b, used_c = {w[0] for w in words}, {w[1] for w in words}
    initials = _match_initials(b, c, used_b, used_c)
    m: Json = {
        "words": words,
        "initials": initials,
        "left_b": [i for i in range(len(b)) if i not in used_b],
        "left_c": [j for j in range(len(c)) if j not in used_c],
        "moved": _crossing(
            [(i, j) for i, j, _, _ in words] + [(i, j) for i, j, _ in initials]
        ),
    }
    _name_reasons(reasons, m, b, c, cfg)
    out = make_outcome(reasons, False, base, cand)
    conflict = bool(m["left_b"] and m["left_c"])

    def mark(bi: int | None, ci: int | None, kind: str) -> None:
        """Highlight a word of the base and/or of the candidate."""
        if bi is not None:
            out["base_spans"].append((b[bi]["start"], b[bi]["end"], kind))
        if ci is not None:
            out["cand_spans"].append((c[ci]["start"], c[ci]["end"], kind))

    for i, j, _, _ in words:
        mark(i, j, "moved" if i in m["moved"] else "match")
    for i, j, kind in initials:
        mark(i, j, "match" if kind == "initial_exact" else "initial")
    for i in m["left_b"]:
        mark(i, None, "conflict" if conflict else "missing")
    for j in m["left_c"]:
        mark(None, j, "conflict" if conflict else "extra")
    return out
