"""
File: short_text.py
Purpose: Short text: gender, relationship, nationality, names of places and bodies.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt

from .addresses import _compare_lists
from .addresses import _highlight_list
from .addresses import _spans
from .common import _WORD
from .common import Json
from .common import Span
from .common import add_reason
from .common import failure
from .common import fold
from .common import has_foreign_letters
from .common import make_outcome
from .common import word_relation

# Two ways of comparing. With a kind that has a word list in the settings ("gender"), both sides are turned
# into one term and compared. Without one, the words are paired, with a little room for spelling.


def _join_letters(tokens: list[Json]) -> list[Json]:
    """Join a run of single letters into one word, so 'M.S.' is read the same way as 'MS'."""
    joined: list[Json] = []
    run: list[Json] = []
    for token in [*tokens, None]:
        if token is not None and len(token["norm"]) == 1 and token["norm"].isalpha():
            run.append(token)
            continue
        if len(run) > 1:
            joined.append(
                {
                    "norm": "".join(t["norm"] for t in run),
                    "start": run[0]["start"],
                    "end": run[-1]["end"],
                }
            )
        else:
            joined.extend(run)
        run = []
        if token is not None:
            joined.append(token)
    return joined


def parse_text(text: str, cfg: Json, side: str, kind: str) -> Json:
    """Read short text into a known term when there is one, and into words either way.

    Args:
        text: Raw text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.
        kind: Vocabulary name (gender, relationship, ...) or an empty string.

    Returns:
        The parsed text ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt, tc = cfg["_rt"], cfg["text"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    term = rt["vocabularies"].get(kind, {}).get(" ".join(fold(text).split()))
    found: list[Json] = []
    foreign = False
    for match in _WORD.finditer(text):
        if has_foreign_letters(match.group()):
            foreign = True
            ignored.append((match.start(), match.end(), "ignored"))
            continue
        found.append(
            {"norm": fold(match.group()), "start": match.start(), "end": match.end()}
        )

    words: list[Json] = []
    for token in _join_letters(found):
        norm = token["norm"]
        if norm in rt["text_ignored"]:
            ignored.append((token["start"], token["end"], "ignored"))
            continue
        # A short form may stand for more than one word: "MS" -> "master science".
        for piece in rt["text_abbreviations"].get(norm, norm).split():
            stem = (
                piece[:-1]
                if len(piece) > 4 and piece.endswith("s") and not piece.endswith("ss")
                else piece
            )
            words.append(
                {
                    "norm": piece,
                    "key": stem,
                    "start": token["start"],
                    "end": token["end"],
                }
            )
    if term is None and not words:
        code = "UNSUPPORTED_SCRIPT" if foreign else "UNPARSEABLE"
        return failure(code, f"No text could be read from the {side} value.")
    if len(words) > tc["max_tokens"]:
        return failure("TOO_LONG", f"The {side} text has too many words.")
    if foreign:
        add_reason(
            reasons,
            cfg,
            "NON_LATIN_TEXT_IGNORED",
            f"Non-Latin text in the {side} value was ignored.",
        )
    return {
        "ok": True,
        "raw": text,
        "kind": kind,
        "term": term,
        "words": words,
        "ignored": ignored,
        "reasons": reasons,
        "normalized": term or " ".join(w["norm"] for w in words),
    }


def compare_texts(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two short texts, by known term when both sides have one, otherwise word by word.

    Args:
        base: Parsed base text.
        cand: Parsed candidate text.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons and highlight spans.
    """
    tc = cfg["text"]
    reasons = [*base["reasons"], *cand["reasons"]]
    if base["term"] is not None and cand["term"] is not None:
        same = base["term"] == cand["term"]
        if same:
            code = (
                "EXACT"
                if base["raw"].strip() == cand["raw"].strip()
                else "NORMALIZED_EQUAL"
            )
            add_reason(reasons, cfg, code, "The values mean the same thing.")
        else:
            add_reason(
                reasons,
                cfg,
                "TEXT_DIFFERENT",
                f"The values mean different things ({base['term']} and {cand['term']}).",
            )
        out = make_outcome(reasons, same, base, cand)
        out["base_spans"] += [
            (w["start"], w["end"], "match" if same else "conflict")
            for w in base["words"]
        ]
        out["cand_spans"] += [
            (w["start"], w["end"], "match" if same else "conflict")
            for w in cand["words"]
        ]
        return out

    def word_rel(a: str, b: str) -> tuple[str, float] | None:
        return word_relation(a, b, tc["fuzzy_min_length"], tc["edit_allowance"])

    result = _compare_lists(
        [w["key"] for w in base["words"]],
        [w["key"] for w in cand["words"]],
        word_rel,
        tc["min_coverage"],
    )
    ordered = [w["norm"] for w in base["words"]] == [w["norm"] for w in cand["words"]]
    same = False
    if ordered:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The values are the same.")
        same = True
    elif result["status"] == "match":
        add_reason(
            reasons,
            cfg,
            "TOKEN_ORDER_DIFFERENT",
            "The same words appear in a different order.",
        )
    elif result["status"] == "partial" and not (result["left_b"] or result["left_c"]):
        add_reason(
            reasons,
            cfg,
            "SPELLING_VARIANT",
            "Some words are spelled slightly differently.",
        )
    elif result["status"] == "partial":
        add_reason(
            reasons,
            cfg,
            "WORDS_PARTIAL",
            "Some words differ, but enough of them match.",
        )
    elif result["status"] == "subset":
        missing = [base["words"][i]["norm"] for i in result["left_b"]]
        extra = [cand["words"][j]["norm"] for j in result["left_c"]]
        if missing:
            add_reason(
                reasons,
                cfg,
                "MISSING_TOKEN",
                f"The candidate lacks {', '.join(missing)}.",
            )
        if extra:
            add_reason(
                reasons,
                cfg,
                "EXTRA_TOKEN",
                f"The candidate has the extra {', '.join(extra)}.",
            )
    else:
        add_reason(
            reasons, cfg, "WORDS_MISMATCH", "The words of the two values do not match."
        )
    out = make_outcome(reasons, same, base, cand)
    _highlight_list(result, _spans(base["words"]), _spans(cand["words"]), out)
    return out
