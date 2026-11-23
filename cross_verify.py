from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from rapidfuzz.distance import OSA

log = logging.getLogger("cross_verify")
Json = dict[str, Any]
Span = tuple[int, int, str]  # (start, end, kind) over the raw text, used for highlights


class CrossVerifyError(Exception):
    """Base class of every error raised here."""


class ConfigError(CrossVerifyError):
    """The configuration file is missing or invalid."""


class InputError(CrossVerifyError, ValueError):
    """The request itself is malformed (a bad data value is never an error, it is red)."""


class ModeNotImplementedError(CrossVerifyError, NotImplementedError):
    """hybrid and llm are not developed yet."""


REASONS: dict[str, str] = {  # reason code -> severity. The colour is the worst severity of the reasons found.
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
    """Append a reason once. The config can change its severity (severity_overrides)."""
    if any(r["code"] == code for r in reasons):
        return
    severity = cfg["severity_overrides"].get(code, REASONS[code])
    reasons.append({"code": code, "severity": severity, "message": message})



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
    """Fail at start-up, with every problem listed, instead of in the middle of a request."""
    errors = [f"{path}: missing" for path in _REQUIRED if not _has(cfg, path)]
    if not errors:
        if cfg["mode"] not in MODES:
            errors.append(f"mode must be one of {', '.join(MODES)}")
        errors += [f"severity_overrides: bad entry {k}" for k, v in cfg["severity_overrides"].items()
                   if k not in REASONS or v not in FLAG_OF_SEVERITY]  # fmt: skip
    if errors:
        raise ConfigError("invalid configuration: " + "; ".join(errors))


def _phrase_regex(phrases: Sequence[str]) -> str:
    """Regex alternatives for phrases, longest first, spaces matching any whitespace."""
    return "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in sorted(phrases, key=len, reverse=True))


def load_config(path: str | os.PathLike[str] | None = None) -> Json:
    """Read the config file (argument, else $CROSS_VERIFY_CONFIG_PATH, else next to this file)."""
    target = Path(path or os.environ.get(ENV_CONFIG_PATH) or Path(__file__).with_name(DEFAULT_CONFIG_NAME))
    try:
        cfg = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {target}") from exc
    except (OSError, ValueError) as exc:
        raise ConfigError(f"configuration file {target} is not readable JSON: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"configuration file {target} must hold a JSON object")
    return prepare_config(cfg)


def prepare_config(raw: Mapping[str, Any]) -> Json:
    """Validate a config mapping and add the lookup tables built from it (under '_rt')."""
    cfg: Json = json.loads(json.dumps(raw))  # private copy, plain JSON only
    check_config(cfg)
    cfg["config_hash"] = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    name, addr = cfg["name"], cfg["address"]
    cities = {fold(city): fold(city) for city in addr["cities"]}
    for city, aliases in addr["cities"].items():
        cities.update({fold(alias): fold(city) for alias in aliases})
    cfg["_rt"] = {
        "placeholders": frozenset(fold(p) for p in cfg["missing_placeholders"]),
        "care_of": re.compile(rf"(?<![a-z0-9])(?:{_phrase_regex(cfg['care_of_markers'])})(?![a-z0-9])", re.IGNORECASE),
        "name_label": re.compile(rf"\s*(?:{_phrase_regex(name['labels'])})\s*[:\-\u2013]\s*", re.IGNORECASE),
        "dob_label": re.compile(
            rf"(?<![a-z0-9])(?:{_phrase_regex(cfg['dob']['labels'])})(?![a-z0-9])\s*[:\-]?\s*", re.IGNORECASE
        ),
        "address_label": re.compile(rf"\s*(?:{_phrase_regex(addr['labels'])})\s*[:\-\u2013]\s*", re.IGNORECASE),
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
    idc, amount, email, phone, text = (cfg[k] for k in ("id", "amount", "email", "phone", "text"))
    currencies = {fold(symbol): code for symbol, code in amount["currencies"].items()}
    scales = {fold(word): float(factor) for word, factor in amount["scales"].items()}
    vocabularies = {
        kind: {fold(spelling): term for term, spellings in terms.items() for spelling in [term, *spellings]}
        for kind, terms in text["vocabularies"].items()
    }
    return {
        "id_label": re.compile(rf"\s*(?:{_phrase_regex(idc['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*", re.IGNORECASE),
        "id_patterns": {kind: re.compile(pattern) for kind, pattern in idc["patterns"].items()},
        "id_lookalikes": {str(k).upper(): str(v).upper() for k, v in idc["lookalikes"].items()},
        "id_mask_run": re.compile(rf"X{{{int(idc['mask_run_min'])},}}"),
        "amount_label": re.compile(rf"\s*(?:{_phrase_regex(amount['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*", re.IGNORECASE),
        "currency": re.compile(rf"(?<![a-z])(?:{_phrase_regex(list(amount['currencies']))})(?![a-z])", re.IGNORECASE),
        "currencies": currencies,
        "scale_after": re.compile(rf"[\s\-]*(?:{_phrase_regex(list(scales))})(?![a-z])", re.IGNORECASE),
        "scales": scales,
        "email_label": re.compile(rf"\s*(?:{_phrase_regex(email['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*", re.IGNORECASE),
        "email_dot_domains": {fold(d) for d in email["ignore_dots_domains"]},
        "phone_label": re.compile(rf"\s*(?:{_phrase_regex(phone['labels'])})(?![a-z0-9])\s*[:\-\u2013]?\s*", re.IGNORECASE),
        "text_abbreviations": {fold(k): fold(v) for k, v in text["abbreviations"].items()},
        "text_ignored": {fold(w) for w in text["ignored_words"]},
        "vocabularies": vocabularies,
    }


# =============================================================================
# 3. Text helpers
# =============================================================================
_WORD = re.compile(r"(?:[^\W_]|[\u0300-\u036f])+(?:['\u2019](?:[^\W_]|[\u0300-\u036f])+)*")  # letters and digits


def fold(text: str) -> str:
    """Lower-case and drop accents and invisible characters: 'José' -> 'jose'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        ch for ch in decomposed if not unicodedata.combining(ch) and unicodedata.category(ch) not in ("Cf", "Cc")
    )


def has_foreign_letters(text: str) -> bool:
    """True for letters outside the Latin script (Devanagari, Tamil, ...). Not supported yet."""
    return any(ch.isalpha() and ord(ch) > 0x24F for ch in text)


def ascii_digits(text: str) -> str:
    """Turn Devanagari, Tamil, full-width ... digits into 0-9, keeping the length."""
    return "".join(str(unicodedata.decimal(ch)) if unicodedata.category(ch) == "Nd" else ch for ch in text)


def is_missing(value: Any, cfg: Json) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and fold(value).strip() in cfg["_rt"]["placeholders"] | {""}


def show(value: Any) -> str | None:
    """The text shown as 'raw'. None when the value is not text, a number or a date."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, (dt.date, str)):
        return value if isinstance(value, str) else value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)
    return None


def build_segments(raw: str, spans: Sequence[Span]) -> list[Json]:
    """Cut the raw text into pieces for highlighting. Joining the pieces gives back the raw text."""
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
    return {"text": text, "start": start, "end": end, "kind": kind or ("text" if text.strip() else "space")}


def word_relation(a: str, b: str, min_length: int, table: Sequence[Sequence[int]]) -> tuple[str, float] | None:
    """How two folded words relate: ('exact'|'spelling', similarity) or None. Used for address words."""
    if a == b:
        return "exact", 1.0
    longest = max(len(a), len(b))
    allowed = max((edits for min_len, edits in table if longest >= min_len), default=0)
    distance = OSA.distance(a, b)
    if min(len(a), len(b)) >= min_length and 0 < distance <= allowed:
        return "spelling", 1.0 - distance / longest
    return None


def pair_up(left: Sequence[str], right: Sequence[str], relate: Any) -> list[tuple[int, int, str, float]]:
    """One-to-one pairing of two word lists: best similarity first, nearest position as tie-break."""
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


def make_outcome(reasons: list[Json], exact: bool, base: Json, cand: Json, **extra: Any) -> Json:
    """What every compare_* function returns."""
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
    """A value that could not be parsed. parse_* return this."""
    return {"ok": False, "code": code, "message": message}


# =============================================================================
# 4. Names
# =============================================================================
_VOWELS = set("aeiou")


def parse_name(raw: str, cfg: Json, side: str) -> Json:
    """Split a name into folded words with their position in the raw text."""
    rt, nc = cfg["_rt"], cfg["name"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start, end = 0, len(raw)
    label = rt["name_label"].match(raw)
    if label:
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} name.")
    care = rt["care_of"].search(raw, start)
    if care:  # "Nishanth S/O Ramesh": keep only the name before it
        ignored.append((care.start(), len(raw), "ignored"))
        end = care.start()
        add_reason(reasons, cfg, "CARE_OF_REMOVED", f"The 'son of / wife of' part was removed from the {side} name.")

    words: list[Json] = []
    foreign = False
    for match in _WORD.finditer(raw, start, end):
        if has_foreign_letters(match.group()):
            foreign = True
            ignored.append((match.start(), match.end(), "ignored"))
            continue
        norm = "".join(ch for ch in fold(match.group()) if ch.isalpha())  # digits inside a word are OCR noise
        if norm:
            words.append({"norm": norm, "start": match.start(), "end": match.end()})

    while len(words) > 1:  # leading titles: Mr, Dr, Shri ... (never the only word)
        if words[0]["norm"] in rt["honorifics"]:
            ignored.append((words[0]["start"], words[0]["end"], "ignored"))
            add_reason(reasons, cfg, "HONORIFIC_IGNORED", f"A title was ignored in the {side} name.")
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
                {"norm": ch, "start": word["start"] + k, "end": word["start"] + k + 1} for k, ch in enumerate(norm)
            ]
        else:
            tokens.append(word)

    if foreign and not tokens:
        return failure("UNSUPPORTED_SCRIPT", f"The {side} name is not written in Latin letters.")
    if not tokens:
        return failure("UNPARSEABLE", f"No name could be read from the {side} value.")
    if len(tokens) > nc["max_tokens"]:
        return failure("TOO_LONG", f"The {side} name has too many words.")
    if foreign:
        add_reason(reasons, cfg, "NON_LATIN_TEXT_IGNORED", f"Non-Latin text in the {side} name was ignored.")
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
        if b and a["norm"] + b["norm"] in words and a["norm"] not in words and b["norm"] not in words:
            out.append({"norm": a["norm"] + b["norm"], "start": a["start"], "end": b["end"], "joined": True})
            i += 2
        else:
            out.append(a)
            i += 1
    return out


def _match_initials(b: list[Json], c: list[Json], used_b: set[int], used_c: set[int]) -> list[tuple[int, int, str]]:
    """Pair initials: the same letter on both sides, or an initial standing for a leftover word."""
    pairs: list[tuple[int, int, str]] = []

    def take(i: int, j: int, kind: str) -> None:
        pairs.append((i, j, kind))
        used_b.add(i)
        used_c.add(j)

    for i in range(len(b)):
        for j in range(len(c)):
            if i not in used_b and j not in used_c and _is_initial(b[i]) and b[i]["norm"] == c[j]["norm"]:
                take(i, j, "initial_exact")
    for i in range(len(b)):  # base initial -> candidate word starting with it
        if i not in used_b and _is_initial(b[i]):
            for j in range(len(c)):
                if j not in used_c and not _is_initial(c[j]) and c[j]["norm"].startswith(b[i]["norm"]):
                    take(i, j, "initial_expanded")
                    break
    for j in range(len(c)):  # candidate initial -> base word starting with it
        if j not in used_c and _is_initial(c[j]):
            for i in range(len(b)):
                if i not in used_b and not _is_initial(b[i]) and b[i]["norm"].startswith(c[j]["norm"]):
                    take(i, j, "initial_expanded")
                    break
    return pairs


def _crossing(pairs: list[tuple[int, int]]) -> set[int]:
    """Base positions of pairs whose order differs between the two names."""
    return {i for i, j in pairs for i2, j2 in pairs if (i < i2 and j > j2) or (i > i2 and j < j2)}


def _name_reasons(reasons: list[Json], m: Json, b: list[Json], c: list[Json], cfg: Json) -> None:
    """Turn the pairing result into reasons."""
    if m["moved"]:
        add_reason(reasons, cfg, "TOKEN_ORDER_DIFFERENT", "The same name parts appear in a different order.")
    if any(kind == "initial_expanded" for _, _, kind in m["initials"]):
        add_reason(reasons, cfg, "INITIAL_EXPANDED", "An initial stands for a full word.")

    words_b = [b[i]["norm"] for i in m["left_b"] if not _is_initial(b[i])]
    words_c = [c[j]["norm"] for j in m["left_c"] if not _is_initial(c[j])]
    if m["left_b"] and m["left_c"]:  # each side has something the other lacks: a word was replaced
        left_b = ", ".join(b[i]["norm"] for i in m["left_b"])
        left_c = ", ".join(c[j]["norm"] for j in m["left_c"])
        add_reason(
            reasons, cfg, "TOKEN_CONFLICT", f"'{left_c}' in the candidate does not match '{left_b}' in the base."
        )
        return
    if words_b:
        add_reason(reasons, cfg, "MISSING_TOKEN", f"The candidate lacks {', '.join(words_b)}.")
    if words_c:
        add_reason(reasons, cfg, "EXTRA_TOKEN", f"The candidate has the extra {', '.join(words_c)}.")
    if len(m["left_b"]) > len(words_b):
        add_reason(reasons, cfg, "MISSING_INITIALS", "The candidate lacks some initials.")
    if len(m["left_c"]) > len(words_c):
        add_reason(reasons, cfg, "EXTRA_INITIALS", "The candidate has extra initials.")
    if not m["words"] and len(m["initials"]) < cfg["name"]["initials_only_min"]:
        add_reason(reasons, cfg, "INSUFFICIENT_NAME", "Too little of the name is present to confirm a match.")


def compare_names(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two parsed names. ('today' is unused here, all compare_* share one signature.)"""
    b, c = base["tokens"], cand["tokens"]
    reasons = [*base["reasons"], *cand["reasons"]]
    if [t["norm"] for t in b] == [t["norm"] for t in c]:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The names are the same.")
        out = make_outcome(reasons, True, base, cand)
        out["base_spans"] += [(t["start"], t["end"], "match") for t in b]
        out["cand_spans"] += [(t["start"], t["end"], "match") for t in c]
        return out

    b, c = _join_neighbours(b, c), _join_neighbours(c, b)
    if any(t.get("joined") for t in (*b, *c)):
        add_reason(
            reasons, cfg, "SPACING_DIFFERENCE", "A name is written as one word on one side and two on the other."
        )

    def relate(x: str, y: str) -> tuple[str, float] | None:
        return ("exact", 1.0) if x == y else None  # a name is compared letter for letter: Vinay and Vijay differ

    full_b = [i for i, t in enumerate(b) if not _is_initial(t)]
    full_c = [j for j, t in enumerate(c) if not _is_initial(t)]
    found = pair_up([b[i]["norm"] for i in full_b], [c[j]["norm"] for j in full_c], relate)
    words = [(full_b[i], full_c[j], kind, sim) for i, j, kind, sim in found]
    used_b, used_c = {w[0] for w in words}, {w[1] for w in words}
    initials = _match_initials(b, c, used_b, used_c)
    m: Json = {
        "words": words,
        "initials": initials,
        "left_b": [i for i in range(len(b)) if i not in used_b],
        "left_c": [j for j in range(len(c)) if j not in used_c],
        "moved": _crossing([(i, j) for i, j, _, _ in words] + [(i, j) for i, j, _ in initials]),
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


# =============================================================================
# 5. Dates of birth
# =============================================================================
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
# A date of birth is day, month, year in that order (month as a number or a name, four-digit year).
# Green only when day, month and year are all equal. Any other date is red. A year-first date (1998-03-12) is also read.
_SEP = r"[\s\-/.,]*"
_NUMERIC = re.compile(r"(?<!\d)(\d{1,4})\s*([/\-.])\s*(\d{1,2})\s*\2\s*(\d{1,4})(?!\d)")  # 12-03-1998
_DAY_MONTH_NAME = re.compile(rf"(?<![a-z\d])(\d{{1,2}})(?:st|nd|rd|th)?{_SEP}([a-z]{{3,9}})\.?{_SEP}(\d{{4}})(?!\d)")
_PARTS = ("day", "month", "year")


def _span(m: re.Match[str], group: int, offset: int) -> tuple[int, int]:
    return m.start(group) + offset, m.end(group) + offset


def _build(year: int, month: int, day: int, spans: dict[str, tuple[int, int]], today: dt.date, max_age: int) -> Json:
    """One date. An error if it does not exist (UNPARSEABLE) or is in the future or too old (DATE_IMPLAUSIBLE)."""
    try:
        when = dt.date(year, month, day)
    except ValueError:
        return {"error": "UNPARSEABLE"}
    if when > today or year < today.year - max_age:
        return {"error": "DATE_IMPLAUSIBLE"}
    return {"year": year, "month": month, "day": day, "spans": spans}


def _numeric_date(text: str, offset: int, today: dt.date, max_age: int) -> Json | None:
    """12-03-1998, 12/03/1998, 12.03.1998 (day, month, year), or year first: 1998-03-12."""
    m = _NUMERIC.search(text)
    if not m:
        return None
    first, last = len(m.group(1)), len(m.group(4))
    if first <= 2 and last == 4:  # day, month, year
        groups = {"day": 1, "month": 3, "year": 4}
    elif first == 4 and last <= 2:  # year, month, day
        groups = {"year": 1, "month": 3, "day": 4}
    else:  # for example a two-digit year
        return None
    value = {part: int(m.group(group)) for part, group in groups.items()}
    spans = {part: _span(m, group, offset) for part, group in groups.items()}
    return _build(value["year"], value["month"], value["day"], spans, today, max_age)


def _named_month_date(text: str, offset: int, today: dt.date, max_age: int) -> Json | None:
    """12 March 1998, 12th March, 1998, 12-Mar-1998 (day, month name, year)."""
    for m in _DAY_MONTH_NAME.finditer(text):
        if m.group(2) in _MONTHS:
            spans = {"day": _span(m, 1, offset), "month": _span(m, 2, offset), "year": _span(m, 3, offset)}
            return _build(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)), spans, today, max_age)
    return None


def _read_date(text: str, offset: int, today: dt.date, max_age: int) -> Json | None:
    """Try each date format in turn. None when the text holds no full date."""
    for reader in (_numeric_date, _named_month_date):
        found: Json | None = reader(text, offset, today, max_age)
        if found:
            return found
    return None


def _iso(found: Json) -> str:
    return f"{found['year']:04d}-{found['month']:02d}-{found['day']:02d}"


def parse_dob(value: Any, text: str, cfg: Json, side: str, today: dt.date) -> Json:
    """Read a date of birth. It needs a day, a month and a four-digit year."""
    reasons: list[Json] = []
    ignored: list[Span] = []
    max_age = cfg["dob"]["max_age"]
    found: Json | None
    if isinstance(value, dt.date):  # a real date object: nothing to read
        day = value.date() if isinstance(value, dt.datetime) else value
        found = _build(day.year, day.month, day.day, {}, today, max_age)
    else:
        lowered = "".join(low if len(low := ch.lower()) == 1 else ch for ch in ascii_digits(text))
        start = 0
        label = cfg["_rt"]["dob_label"].search(lowered)
        if label:
            start = label.end()
            ignored.append((label.start(), label.end(), "ignored"))
            add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} date.")
        found = _read_date(lowered[start:], start, today, max_age)
    if found is None:
        return failure("UNPARSEABLE", f"No full date (day, month and year) could be read from the {side} value.")
    if "error" in found:
        message = (
            "is in the future or too far in the past" if found["error"] == "DATE_IMPLAUSIBLE" else "is not a real date"
        )
        return failure(found["error"], f"The {side} date {message}.")
    return {
        "ok": True,
        "raw": text,
        **found,  # year, month, day, spans
        "ignored": ignored,
        "reasons": reasons,
        "normalized": _iso(found),
    }


def _digits(found: Json) -> str:
    return f"{found['year']:04d}{found['month']:02d}{found['day']:02d}"


def compare_dobs(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two parsed dates part by part (day, month, year). Green only when all three are equal."""
    reasons = [*base["reasons"], *cand["reasons"]]
    equal = {part: base[part] == cand[part] for part in _PARTS}
    same = all(equal.values())
    if same:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The dates are the same.")
    else:
        differing = [p for p in _PARTS if not equal[p]]
        near = OSA.distance(_digits(base), _digits(cand)) == 1  # one digit off: maybe a typing error
        add_reason(reasons, cfg, "DATE_DIFFERENT", f"The {', '.join(differing)} differ.")
        if near:
            add_reason(
                reasons, cfg, "POSSIBLE_TYPO", "The dates differ by a single digit, which may be a typing error."
            )

    out = make_outcome(reasons, same, base, cand)
    out["components"] = []
    for part in _PARTS:
        kind = "match" if equal[part] else "conflict"
        if part in base["spans"]:
            out["base_spans"].append((*base["spans"][part], kind))
        if part in cand["spans"]:
            out["cand_spans"].append((*cand["spans"][part], kind))
        out["components"].append({"component": part, "base": base[part], "candidate": cand[part], "relation": kind})
    return out


# =============================================================================
# 6. Addresses
# =============================================================================
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


def _address_tokens(text: str, regions: list[tuple[int, int]], skip: tuple[int, int] | None) -> list[Json]:
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
                    {"norm": fold(part.group()), "start": m.start() + part.start(), "end": m.start() + part.end()}
                )
    return tokens


def parse_address(text: str, cfg: Json, side: str) -> Json:
    """Split an address into pincode, city, numbers and place words."""
    rt, ac = cfg["_rt"], cfg["address"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    digits = ascii_digits(text)
    start = 0
    label = rt["address_label"].match(digits)
    if label:
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} address.")

    segments = [(m.start(), m.end()) for m in _SEGMENT.finditer(digits, start)]
    regions: list[tuple[int, int]] = []
    for a, b in segments:  # a line like "S/O Ramesh" is not part of the address
        care = rt["care_of"].match(digits, a + len(digits[a:b]) - len(digits[a:b].lstrip()), b)
        if care and len(segments) > 1:
            ignored.append((a, b, "ignored"))
            add_reason(
                reasons, cfg, "CARE_OF_REMOVED", f"The 'care of / son of' line was removed from the {side} address."
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
        return failure("UNSUPPORTED_SCRIPT", f"The {side} address is not written in Latin letters.")
    if foreign:
        add_reason(reasons, cfg, "NON_LATIN_TEXT_IGNORED", f"Non-Latin text in the {side} address was ignored.")
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
    for i, token in enumerate(tokens):  # "2nd cross", "cross 2", "sector 5" become one item: "cross:2"
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
            if sum(ch.isdigit() for ch in norm) <= 6:  # longer digit strings are phone numbers and the like
                numbers.append(
                    {
                        "value": str(int(ordinal.group(1))) if ordinal else norm,
                        "start": token["start"],
                        "end": token["end"],
                    }
                )
        elif len(norm) > 2 and norm.isalpha():  # one and two letter words ("KA", "MG") say too little
            stem = norm[:-1] if len(norm) > 4 and norm.endswith("s") and not norm.endswith("ss") else norm
            words.append({"norm": norm, "key": stem, "start": token["start"], "end": token["end"]})

    if not (pincode or city or numbers or words):
        return failure("UNPARSEABLE", f"No address could be read from the {side} value.")
    parts = [" ".join(n["value"] for n in numbers), " ".join(w["norm"] for w in words), city or "", pincode or ""]
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
    b_keys: Sequence[str], c_keys: Sequence[str], relate: Any, min_coverage: float | None = None
) -> Json:
    """Pair two lists of items and say how well they agree.

    status: match | partial (spelling or prefix) | subset (one side has extra items)
            | mismatch (both sides have items the other lacks) | absent_one | absent_both
    """
    pairs = pair_up(b_keys, c_keys, relate)
    left_b = [i for i in range(len(b_keys)) if i not in {p[0] for p in pairs}]
    left_c = [j for j in range(len(c_keys)) if j not in {p[1] for p in pairs}]
    coverage = 2 * sum(p[3] for p in pairs) / (len(b_keys) + len(c_keys)) if b_keys or c_keys else 1.0
    if not b_keys and not c_keys:
        status = "absent_both"
    elif not b_keys or not c_keys:
        status = "absent_one"
    elif left_b and left_c:
        status = "partial" if min_coverage is not None and coverage >= min_coverage else "mismatch"
    elif left_b or left_c:
        status = "subset"
    else:
        status = "match" if all(p[2] == "exact" for p in pairs) else "partial"
    return {"status": status, "pairs": pairs, "left_b": left_b, "left_c": left_c}


def _highlight_list(
    result: Json, b_spans: Sequence[tuple[int, int]], c_spans: Sequence[tuple[int, int]], out: Json
) -> None:
    """Add highlight spans for a list component to the outcome."""
    for i, j, kind, _ in result["pairs"]:
        out["base_spans"].append((*b_spans[i], "match" if kind == "exact" else "spelling"))
        out["cand_spans"].append((*c_spans[j], "match" if kind == "exact" else "spelling"))
    conflict = result["status"] == "mismatch"
    out["base_spans"] += [(*b_spans[i], "conflict" if conflict else "missing") for i in result["left_b"]]
    out["cand_spans"] += [(*c_spans[j], "conflict" if conflict else "extra") for j in result["left_c"]]


# (part, status) -> (reason code, message). A part that matches needs no reason.
_ADDRESS_NOTES = {
    ("pincode", "near"): ("PINCODE_NEAR", "The pincodes differ in the last digits only."),
    ("pincode", "mismatch"): ("PINCODE_MISMATCH", "The pincodes differ."),
    ("city", "mismatch"): ("CITY_MISMATCH", "The cities differ."),
    ("number", "mismatch"): ("NUMBER_MISMATCH", "The house or street numbers differ."),
    ("number", "subset"): ("NUMBER_SUBSET", "One address has a house or street number the other lacks."),
    ("number", "partial"): ("NUMBER_SUBSET", "A house number matches only in its first part (12 and 12/3)."),
    ("text", "mismatch"): ("WORDS_MISMATCH", "The place names in the two addresses do not match."),
    ("text", "subset"): ("INCOMPLETE_ADDRESS", "One address has place words the other lacks."),
    ("text", "partial"): ("WORDS_PARTIAL", "Some place words differ, but enough of them match."),
    ("text", "spelling"): ("SPELLING_VARIANT", "Some place words are spelled slightly differently."),
}  # fmt: skip
_ADDRESS_PARTS = {"pincode": "pincode", "city": "city", "number": "house or street numbers", "text": "place words"}


def compare_addresses(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two parsed addresses part by part (pincode, city, numbers, place words)."""
    ac = cfg["address"]
    reasons = [*base["reasons"], *cand["reasons"]]

    def number_relation(a: str, b: str) -> tuple[str, float] | None:
        if a == b:
            return "exact", 1.0
        return ("prefix", ac["prefix_credit"]) if a.split("/", 1)[0] == b or b.split("/", 1)[0] == a else None

    def word_rel(a: str, b: str) -> tuple[str, float] | None:
        return word_relation(a, b, ac["fuzzy_min_length"], ac["edit_allowance"])

    numbers = _compare_lists(
        [n["value"] for n in base["numbers"]], [n["value"] for n in cand["numbers"]], number_relation
    )
    text = _compare_lists(
        [w["key"] for w in base["words"]], [w["key"] for w in cand["words"]], word_rel, ac["text_min_coverage"]
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
    present = {"pincode": base["pincode"], "city": base["city"], "number": base["numbers"], "text": base["words"]}
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
    if not (statuses["pincode"] == "match" or any(pair[2] == "exact" for pair in numbers["pairs"])):
        add_reason(reasons, cfg, "NO_ANCHOR_MATCH", "Neither the pincode nor a house number matches.")
    exact = all(s in ("match", "absent_both") for s in statuses.values())
    if exact:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The addresses are the same.")

    out = make_outcome(reasons, exact, base, cand)

    # ---- highlights, and a part-by-part table for the UI ----
    kinds = {"match": "match", "near": "spelling", "mismatch": "conflict"}
    pin_spans = ([base["pin_span"]] if base["pin_span"] else [], [cand["pin_span"]] if cand["pin_span"] else [])
    for part, (b_spans, c_spans) in (("pincode", pin_spans), ("city", (base["city_spans"], cand["city_spans"]))):
        out["base_spans"] += [(*s, kinds.get(statuses[part], "missing")) for s in b_spans]
        out["cand_spans"] += [(*s, kinds.get(statuses[part], "extra")) for s in c_spans]
    _highlight_list(numbers, _spans(base["numbers"]), _spans(cand["numbers"]), out)
    _highlight_list(text, _spans(base["words"]), _spans(cand["words"]), out)
    values = {
        "pincode": (base["pincode"], cand["pincode"]),
        "city": (base["city"], cand["city"]),
        "number": ([n["value"] for n in base["numbers"]], [n["value"] for n in cand["numbers"]]),
        "text": ([w["norm"] for w in base["words"]], [w["norm"] for w in cand["words"]]),
    }
    out["components"] = [
        {"component": p, "status": statuses[p], "base": b, "candidate": c} for p, (b, c) in values.items()
    ]
    return out


# =============================================================================
# 7. Identity numbers: Aadhaar, PAN, passport, voter ID, driving licence
# =============================================================================
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
    """Read an identity number. With a known kind, a value of the wrong shape is refused."""
    rt = cfg["_rt"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start = 0
    label = rt["id_label"].match(text)
    if label and label.end() < len(text):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} number.")
    value = _id_clean(text[start:])
    if not value:
        return failure("UNPARSEABLE", f"No number could be read from the {side} value.")
    masked = bool(rt["id_mask_run"].search(value))
    pattern = rt["id_patterns"].get(kind)
    # "full" means the value has the shape of a whole number of this kind. A value that has not (a misread
    # character, only the last four digits, plain rubbish) is still compared, but can never come out green.
    full = masked or pattern is None or bool(pattern.fullmatch(value))
    return {"ok": True, "raw": text, "kind": kind, "value": value, "masked": masked, "full": full,
            "span": (start, len(text)), "ignored": ignored, "reasons": reasons, "normalized": value}  # fmt: skip


def compare_ids(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two identity numbers. Green only when the whole number is the same."""
    rt, tail = cfg["_rt"], cfg["id"]["min_visible_tail"]
    reasons = [*base["reasons"], *cand["reasons"]]
    b, c = base["value"], cand["value"]
    masked = base["masked"] or cand["masked"]
    whole = base["full"] and cand["full"]
    same = False
    if whole and b == c:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The numbers are the same.")
        same, kind = True, "match"
    elif b == c:
        add_reason(reasons, cfg, "ID_FORMAT_DOUBTFUL",
                   f"The two values agree, but they are not shaped like a {base['kind'].replace('_', ' ')} number.")  # fmt: skip
        kind = "spelling"
    elif not masked and len(b) == len(c) and _id_shape(b, rt["id_lookalikes"]) == _id_shape(c, rt["id_lookalikes"]):
        add_reason(reasons, cfg, "ID_OCR_VARIANT",
                   "The numbers differ only in characters that look alike (O and 0, I and 1).")  # fmt: skip
        kind = "spelling"
    elif masked or not whole:
        # A bureau prints XXXXXXXX1234, and some records hold only the last digits. Only the end can be
        # compared, so this is never green.
        visible_b, visible_c = rt["id_mask_run"].split(b)[-1], rt["id_mask_run"].split(c)[-1]
        shared = min(len(visible_b), len(visible_c))
        if shared >= tail and visible_b[-shared:] == visible_c[-shared:]:
            add_reason(reasons, cfg, "ID_MASKED" if masked else "ID_PARTIAL",
                       f"One value holds only part of the number. The last {shared} characters agree.")  # fmt: skip
            kind = "spelling"
        else:
            add_reason(reasons, cfg, "ID_DIFFERENT", "The part of the number that can be read does not agree.")
            kind = "conflict"
    elif min(len(b), len(c)) >= tail and (b.endswith(c) or c.endswith(b)):
        add_reason(reasons, cfg, "ID_PARTIAL", "One number holds only the last characters of the other.")
        kind = "spelling"
    else:
        add_reason(reasons, cfg, "ID_DIFFERENT", "The numbers are different.")
        if OSA.distance(b, c) == 1:
            add_reason(reasons, cfg, "POSSIBLE_TYPO",
                       "The numbers differ in one character, which may be a typing error.")  # fmt: skip
        kind = "conflict"
    out = make_outcome(reasons, same, base, cand)
    out["base_spans"].append((*base["span"], kind))
    out["cand_spans"].append((*cand["span"], kind))
    return out


# =============================================================================
# 8. Amounts
# =============================================================================
# "Rs. 12,50,000/-", "1250000", "12.5 lakh" and "INR 1250000.00" are the same amount. Currencies are never
# converted: two different currencies are a mismatch, because a rate belongs to the caller, not here.
_AMOUNT_NUMBER = re.compile(r"-?\d+(?:,\d+)*(?:\.\d+)?")


def parse_amount(text: str, cfg: Json, side: str) -> Json:
    """Read one amount and, when it is printed, its currency."""
    rt = cfg["_rt"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    body = ascii_digits(text)
    start = 0
    label = rt["amount_label"].match(body)
    if label and label.end() < len(body):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} amount.")
    number = _AMOUNT_NUMBER.search(body, start)
    if number is None:
        return failure("UNPARSEABLE", f"No amount could be read from the {side} value.")
    value = float(number.group().replace(",", ""))
    scale = rt["scale_after"].match(body, number.end())  # "12.5 lakh", "₹5 cr"
    if scale is not None:
        value *= rt["scales"][fold(scale.group().strip(" -"))]
    found = rt["currency"].search(body)
    currency = rt["currencies"][fold(found.group())] if found is not None else None
    return {"ok": True, "raw": text, "value": value, "currency": currency,
            "span": (number.start(), scale.end() if scale is not None else number.end()),
            "ignored": ignored, "reasons": reasons,
            "normalized": f"{currency} {value:,.2f}" if currency else f"{value:,.2f}"}  # fmt: skip


def compare_amounts(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two amounts. A rounding or near difference is a warning, a real difference is a mismatch."""
    ac = cfg["amount"]
    reasons = [*base["reasons"], *cand["reasons"]]
    money_b, money_c = base["currency"], cand["currency"]
    clashing = bool(money_b and money_c and money_b != money_c)
    assumed = bool(
        (money_b or money_c) and not (money_b and money_c) and (money_b or money_c) != ac["default_currency"]
    )
    if clashing:
        add_reason(reasons, cfg, "CURRENCY_MISMATCH",
                   f"The amounts are in different currencies ({money_b} and {money_c}).")  # fmt: skip
    elif assumed:
        add_reason(reasons, cfg, "CURRENCY_ASSUMED",
                   f"Only one side names a currency ({money_b or money_c}); the other was read as the same.")  # fmt: skip

    gap = abs(base["value"] - cand["value"])
    largest = max(abs(base["value"]), abs(cand["value"]))
    if gap == 0 and clashing:
        pass  # the numbers agree but the money does not, which the currency reason already says
    elif gap == 0:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The amounts are the same.")
    elif gap <= ac["round_tolerance"]:
        add_reason(reasons, cfg, "AMOUNT_ROUNDED", f"The amounts differ by {gap:,.2f}, which is rounding.")
    elif largest and 100.0 * gap / largest <= ac["near_percent"]:
        add_reason(reasons, cfg, "AMOUNT_NEAR",
                   f"The amounts differ by {gap:,.2f} ({100.0 * gap / largest:.2f} percent).")  # fmt: skip
    else:
        add_reason(reasons, cfg, "AMOUNT_DIFFERENT", f"The amounts differ by {gap:,.2f}.")

    out = make_outcome(reasons, gap == 0 and not (clashing or assumed), base, cand)
    mark = "match" if gap == 0 else "conflict"
    out["base_spans"].append((*base["span"], mark))
    out["cand_spans"].append((*cand["span"], mark))
    money = "conflict" if clashing else "match"
    out["components"] = [
        {"component": "value", "base": base["value"], "candidate": cand["value"], "relation": mark},
        {"component": "currency", "base": money_b, "candidate": money_c, "relation": money},
    ]
    return out


# =============================================================================
# 9. Email addresses and phone numbers
# =============================================================================
_EMAIL = re.compile(r"[^@\s,;<>()]+@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}")


def parse_email(text: str, cfg: Json, side: str) -> Json:
    """Read one email address and work out which mailbox it stands for."""
    rt, ec = cfg["_rt"], cfg["email"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start = 0
    label = rt["email_label"].match(text)
    if label and label.end() < len(text):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} email address.")
    found = _EMAIL.search(text, start)
    if found is None:
        return failure("UNPARSEABLE", f"No email address could be read from the {side} value.")
    local, _, domain = fold(found.group()).partition("@")
    mailbox = local.partition("+")[0] if ec["ignore_tags"] else local
    if domain in rt["email_dot_domains"]:  # gmail ignores dots inside the name
        mailbox = mailbox.replace(".", "")
    return {"ok": True, "raw": text, "local": local, "domain": domain, "mailbox": f"{mailbox}@{domain}",
            "span": (found.start(), found.end()), "ignored": ignored, "reasons": reasons,
            "normalized": f"{local}@{domain}"}  # fmt: skip


def compare_emails(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two email addresses. The same mailbox written differently is a warning."""
    reasons = [*base["reasons"], *cand["reasons"]]
    same = base["normalized"] == cand["normalized"]
    if same:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The email addresses are the same.")
        kind = "match"
    elif base["mailbox"] == cand["mailbox"]:
        add_reason(reasons, cfg, "EMAIL_ALIAS", "The two addresses reach the same mailbox, written differently.")
        kind = "spelling"
    else:
        add_reason(reasons, cfg, "EMAIL_DIFFERENT", "The email addresses are different.")
        if OSA.distance(base["normalized"], cand["normalized"]) == 1:
            add_reason(reasons, cfg, "POSSIBLE_TYPO",
                       "The addresses differ in one character, which may be a typing error.")  # fmt: skip
        kind = "conflict"
    out = make_outcome(reasons, same, base, cand)
    out["base_spans"].append((*base["span"], kind))
    out["cand_spans"].append((*cand["span"], kind))
    parts = ("name", base["local"], cand["local"]), ("domain", base["domain"], cand["domain"])
    out["components"] = [
        {"component": part, "base": left, "candidate": right,
         "relation": "match" if left == right else "conflict"}
        for part, left, right in parts
    ]
    return out


def parse_phone(text: str, cfg: Json, side: str) -> Json:
    """Read one phone number: keep the digits, then take off a country code or a leading zero."""
    rt, pc = cfg["_rt"], cfg["phone"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start = 0
    label = rt["phone_label"].match(text)
    if label and label.end() < len(text):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(reasons, cfg, "LABEL_STRIPPED", f"A label was removed from the {side} phone number.")
    body = text[start:]
    digits = "".join(ch for ch in ascii_digits(body) if ch.isdigit())
    national, country = digits, None
    for code in pc["country_codes"]:
        if digits.startswith(f"00{code}"):  # 0091 98765 43210
            national, country = digits[len(code) + 2 :], code
            break
        # A bare 10-digit number may itself start with the country code, so the length has to fit.
        if digits.startswith(code) and len(digits) == len(code) + pc["national_length"]:
            national, country = digits[len(code) :], code
            break
    if country is None and len(national) == pc["national_length"] + 1 and national.startswith("0"):
        national = national[1:]  # 0 98765 43210
    if len(national) < pc["min_digits"]:
        return failure("UNPARSEABLE", f"No phone number could be read from the {side} value.")
    return {"ok": True, "raw": text, "national": national, "country": country,
            "span": (start, len(text)), "ignored": ignored, "reasons": reasons,
            "normalized": f"+{country} {national}" if country else national}  # fmt: skip


def compare_phones(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two phone numbers. '+91 98765 43210' and '09876543210' are the same number."""
    pc = cfg["phone"]
    tail = pc["min_visible_tail"]
    reasons = [*base["reasons"], *cand["reasons"]]
    b, c = base["national"], cand["national"]
    here, there = base["country"], cand["country"]
    clashing = bool(here and there and here != there)
    assumed = bool((here or there) and not (here and there) and (here or there) != pc["default_country"])
    if clashing:
        add_reason(reasons, cfg, "PHONE_DIFFERENT", f"The country codes differ (+{here} and +{there}).")
    elif assumed:
        add_reason(reasons, cfg, "PHONE_COUNTRY_ASSUMED",
                   f"Only one side names a country code (+{here or there}); the other was read as the same.")  # fmt: skip
    same = False
    if b == c and not clashing:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The phone numbers are the same.")
        same, kind = not assumed, "match"
    elif b == c:
        kind = "conflict"  # the digits agree, the countries do not
    elif min(len(b), len(c)) >= tail and (b.endswith(c) or c.endswith(b)):
        add_reason(reasons, cfg, "PHONE_PARTIAL", "One number holds only the last digits of the other.")
        kind = "spelling"
    else:
        add_reason(reasons, cfg, "PHONE_DIFFERENT", "The phone numbers are different.")
        if OSA.distance(b, c) == 1:
            add_reason(reasons, cfg, "POSSIBLE_TYPO",
                       "The numbers differ in one digit, which may be a typing error.")  # fmt: skip
        kind = "conflict"
    out = make_outcome(reasons, same, base, cand)
    out["base_spans"].append((*base["span"], kind))
    out["cand_spans"].append((*cand["span"], kind))
    return out


# =============================================================================
# 10. Short text: gender, relationship, nationality, and names of places and bodies
# =============================================================================
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
            joined.append({"norm": "".join(t["norm"] for t in run), "start": run[0]["start"], "end": run[-1]["end"]})
        else:
            joined.extend(run)
        run = []
        if token is not None:
            joined.append(token)
    return joined


def parse_text(text: str, cfg: Json, side: str, kind: str) -> Json:
    """Read short text into a known term when there is one, and into words either way."""
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
        found.append({"norm": fold(match.group()), "start": match.start(), "end": match.end()})

    words: list[Json] = []
    for token in _join_letters(found):
        norm = token["norm"]
        if norm in rt["text_ignored"]:
            ignored.append((token["start"], token["end"], "ignored"))
            continue
        # A short form may stand for more than one word: "MS" -> "master science".
        for piece in rt["text_abbreviations"].get(norm, norm).split():
            stem = piece[:-1] if len(piece) > 4 and piece.endswith("s") and not piece.endswith("ss") else piece
            words.append({"norm": piece, "key": stem, "start": token["start"], "end": token["end"]})
    if term is None and not words:
        code = "UNSUPPORTED_SCRIPT" if foreign else "UNPARSEABLE"
        return failure(code, f"No text could be read from the {side} value.")
    if len(words) > tc["max_tokens"]:
        return failure("TOO_LONG", f"The {side} text has too many words.")
    if foreign:
        add_reason(reasons, cfg, "NON_LATIN_TEXT_IGNORED", f"Non-Latin text in the {side} value was ignored.")
    return {"ok": True, "raw": text, "kind": kind, "term": term, "words": words, "ignored": ignored,
            "reasons": reasons, "normalized": term or " ".join(w["norm"] for w in words)}  # fmt: skip


def compare_texts(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two short texts, by known term when both sides have one, otherwise word by word."""
    tc = cfg["text"]
    reasons = [*base["reasons"], *cand["reasons"]]
    if base["term"] is not None and cand["term"] is not None:
        same = base["term"] == cand["term"]
        if same:
            code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
            add_reason(reasons, cfg, code, "The values mean the same thing.")
        else:
            add_reason(reasons, cfg, "TEXT_DIFFERENT",
                       f"The values mean different things ({base['term']} and {cand['term']}).")  # fmt: skip
        out = make_outcome(reasons, same, base, cand)
        out["base_spans"] += [(w["start"], w["end"], "match" if same else "conflict") for w in base["words"]]
        out["cand_spans"] += [(w["start"], w["end"], "match" if same else "conflict") for w in cand["words"]]
        return out

    def word_rel(a: str, b: str) -> tuple[str, float] | None:
        return word_relation(a, b, tc["fuzzy_min_length"], tc["edit_allowance"])

    result = _compare_lists(
        [w["key"] for w in base["words"]], [w["key"] for w in cand["words"]], word_rel, tc["min_coverage"]
    )
    ordered = [w["norm"] for w in base["words"]] == [w["norm"] for w in cand["words"]]
    same = False
    if ordered:
        code = "EXACT" if base["raw"].strip() == cand["raw"].strip() else "NORMALIZED_EQUAL"
        add_reason(reasons, cfg, code, "The values are the same.")
        same = True
    elif result["status"] == "match":
        add_reason(reasons, cfg, "TOKEN_ORDER_DIFFERENT", "The same words appear in a different order.")
    elif result["status"] == "partial" and not (result["left_b"] or result["left_c"]):
        add_reason(reasons, cfg, "SPELLING_VARIANT", "Some words are spelled slightly differently.")
    elif result["status"] == "partial":
        add_reason(reasons, cfg, "WORDS_PARTIAL", "Some words differ, but enough of them match.")
    elif result["status"] == "subset":
        missing = [base["words"][i]["norm"] for i in result["left_b"]]
        extra = [cand["words"][j]["norm"] for j in result["left_c"]]
        if missing:
            add_reason(reasons, cfg, "MISSING_TOKEN", f"The candidate lacks {', '.join(missing)}.")
        if extra:
            add_reason(reasons, cfg, "EXTRA_TOKEN", f"The candidate has the extra {', '.join(extra)}.")
    else:
        add_reason(reasons, cfg, "WORDS_MISMATCH", "The words of the two values do not match.")
    out = make_outcome(reasons, same, base, cand)
    _highlight_list(result, _spans(base["words"]), _spans(cand["words"]), out)
    return out


# =============================================================================
# 11. Decide: reasons -> colour
# =============================================================================
def decide(outcome: Json, cfg: Json) -> Json:
    """The colour is the worst severity among the reasons. Nothing else decides it."""
    reasons: list[Json] = list(outcome["reasons"])
    flag = max((FLAG_OF_SEVERITY[r["severity"]] for r in reasons), key=FLAG_RANK.__getitem__, default="green")
    if flag == "green" and not outcome["exact"] and all(REASONS[r["code"]] == "info" for r in reasons):
        add_reason(reasons, cfg, "DIFFERENCE_UNCLASSIFIED", "The values differ in a way that is not classified.")
        flag = "yellow"  # safety net: never green when the values are not provably equal
    return {"flag": flag, "reasons": reasons}


def build_result(
    source: str,
    source_id: str,
    base_raw: str | None,
    cand_raw: str | None,
    outcome: Json,
    cfg: Json,
) -> Json:
    """One comparison, in the shape the frontend receives."""
    decision = decide(outcome, cfg)
    flag = decision["flag"]
    result: Json = {
        "source": source,
        "id": source_id,
        "raw": cand_raw,
        "normalized": outcome["candidate_normalized"],
        "status": STATUS_OF_FLAG[flag],
        "color": flag,
        "needs_review": flag != "green",
        "decided_by": "fuzzy",
        "reasons": [{k: r[k] for k in ("code", "severity", "message")} for r in decision["reasons"]],
        "fuzzy": {"flag": flag},
        "highlight": {
            "base": build_segments(base_raw, outcome["base_spans"]) if base_raw is not None else [],
            "candidate": build_segments(cand_raw, outcome["cand_spans"]) if cand_raw is not None else [],
        },
    }
    if outcome.get("components"):  # dob and address: a part-by-part table for the UI
        result["components"] = outcome["components"]
    return result


def roll_up(items: Sequence[Json]) -> Json:
    """The worst comparison speaks for the whole group."""
    worst = max(items, key=lambda x: FLAG_RANK[x["color"]])
    return {"status": worst["status"], "color": worst["color"], "needs_review": any(i["needs_review"] for i in items)}


# =============================================================================
# 12. Verify: a list of checks in, one report out
# =============================================================================
COMPARERS = {"name": compare_names, "dob": compare_dobs, "address": compare_addresses,
             "id": compare_ids, "amount": compare_amounts, "email": compare_emails,
             "phone": compare_phones, "text": compare_texts}  # fmt: skip


def parse_value(field_type: str, kind: str, value: Any, cfg: Json, side: str, today: dt.date) -> Json:
    """Check the value, then parse it. Returns {'ok': True, ...} or {'ok': False, 'code', 'message'}."""
    if is_missing(value, cfg):
        return failure("BASE_MISSING" if side == "base" else "MISSING_VALUE", f"The {side} value is missing.")
    text = show(value)
    if text is None:
        return failure("UNPARSEABLE", f"The {side} value is not text, a number or a date.")
    if len(text) > cfg["limits"]["max_text_length"][field_type]:
        return failure("TOO_LONG", f"The {side} value is too long.")
    if field_type == "name":
        return parse_name(text, cfg, side)
    if field_type == "address":
        return parse_address(text, cfg, side)
    if field_type == "id":
        return parse_id(text, cfg, side, kind)
    if field_type == "amount":
        return parse_amount(text, cfg, side)
    if field_type == "email":
        return parse_email(text, cfg, side)
    if field_type == "phone":
        return parse_phone(text, cfg, side)
    if field_type == "text":
        return parse_text(text, cfg, side, kind)
    return parse_dob(value, text, cfg, side, today)


def compare_one(field_type: str, kind: str, base: Json, value: Any, cfg: Json, today: dt.date) -> Json:
    """Compare the parsed base with one candidate value. A value that cannot be read becomes red."""
    cand = parse_value(field_type, kind, value, cfg, "candidate", today)
    broken = base if not base["ok"] else cand if not cand["ok"] else None
    if broken:
        reasons: list[Json] = []
        add_reason(reasons, cfg, broken["code"], broken["message"])
        return {
            "reasons": reasons,
            "exact": False,
            "base_normalized": None,
            "candidate_normalized": None,
            "base_spans": [],
            "cand_spans": [],
        }
    result: Json = COMPARERS[field_type](base, cand, cfg, today)
    return result


def _read_candidates(candidates: Any, where: str, cfg: Json) -> list[Json]:
    if isinstance(candidates, Mapping):  # shorthand {"aadhaar": "...", "pan": "..."}
        candidates = [{"source": k, "value": v} for k, v in candidates.items()]
    if not isinstance(candidates, list) or not candidates:
        raise InputError(f"{where}: 'candidates' must be a non-empty list or object")
    if len(candidates) > cfg["limits"]["max_candidates"]:
        raise InputError(f"{where}: too many candidates (limit {cfg['limits']['max_candidates']})")
    if not all(isinstance(c, Mapping) and isinstance(c.get("source"), str) and c["source"].strip() for c in candidates):
        raise InputError(f"{where}: every candidate needs a 'source' text")
    names = [c["source"].strip() for c in candidates]
    seen: dict[str, int] = {}
    items = []
    for name, candidate in zip(names, candidates, strict=True):
        seen[name] = seen.get(name, 0) + 1  # the same source twice becomes bank#1, bank#2
        unique = f"{name}#{seen[name]}" if names.count(name) > 1 else name
        items.append({"source": name, "id": unique, "value": candidate.get("value")})
    return items


def read_checks(checks: Any, cfg: Json) -> list[Json]:
    """Check the shape of the request and tidy it. Raises InputError when it is malformed."""
    if isinstance(checks, Mapping) and "checks" in checks:
        checks = checks["checks"]
    if not isinstance(checks, list) or not checks:
        raise InputError("the request must be a non-empty list of checks")
    if len(checks) > cfg["limits"]["max_checks"]:
        raise InputError(f"too many checks (limit {cfg['limits']['max_checks']})")
    clean = []
    for n, check in enumerate(checks):
        where = f"checks[{n}]"
        if not isinstance(check, Mapping):
            raise InputError(f"{where}: must be an object")
        asked = str(check.get("type", "")).strip().lower().replace(" ", "_").replace("-", "_")
        field_type, implied = TYPE_ALIASES.get(asked, (asked, ""))
        if field_type not in FIELD_TYPES:
            raise InputError(
                f"{where}: 'type' must be one of {', '.join(FIELD_TYPES)} (or a name for one of them, "
                f"such as pan, aadhaar, mobile, gender)"
            )
        kind = str(check.get("kind", "") or implied).strip().lower().replace(" ", "_")
        if kind and not _known_kind(field_type, kind, cfg):
            raise InputError(f"{where}: 'kind' {kind!r} is not configured for type {field_type!r}")
        if not isinstance(check.get("field"), str) or not check["field"].strip():
            raise InputError(f"{where}: 'field' must be a non-empty text")
        if "base" not in check:
            raise InputError(f"{where}: 'base' is required (use null if unknown)")
        clean.append({"field": check["field"].strip(), "type": field_type, "kind": kind, "base": check["base"],
                      "candidates": _read_candidates(check.get("candidates"), where, cfg)})  # fmt: skip
    return clean


def _known_kind(field_type: str, kind: str, cfg: Json) -> bool:
    """A kind is only accepted when the settings describe it (id patterns, text word lists)."""
    if field_type == "id":
        return kind in cfg["id"]["patterns"]
    if field_type == "text":
        return kind in cfg["text"]["vocabularies"]
    return False


def parse_safely(field_type: str, kind: str, value: Any, cfg: Json, side: str, today: dt.date) -> Json:
    """parse_value, but an unexpected error becomes a failure instead of stopping the request."""
    try:
        return parse_value(field_type, kind, value, cfg, side, today)
    except Exception as exc:
        log.error("parsing failed: %s (%s)", type(exc).__name__, field_type)
        return failure("INTERNAL_ERROR", f"The {side} value could not be processed.")


def compare_safely(field_type: str, kind: str, base: Json, value: Any, cfg: Json, today: dt.date) -> Json:
    """compare_one, but an unexpected error becomes a red INTERNAL_ERROR (and is logged without the values)."""
    try:
        return compare_one(field_type, kind, base, value, cfg, today)
    except Exception as exc:
        log.error("comparison failed: %s (%s)", type(exc).__name__, field_type)
        outcome: Json = {"reasons": [], "exact": False, "base_normalized": None,
                         "candidate_normalized": None, "base_spans": [], "cand_spans": []}  # fmt: skip
        add_reason(outcome["reasons"], cfg, "INTERNAL_ERROR", "The comparison could not be completed.")
        return outcome


def run_checks(checks: Any, cfg: Json, request_id: str | None, today: dt.date | None) -> Json:
    """The whole job: read the request, compare every candidate, roll the results up."""
    request_id = request_id or uuid.uuid4().hex[:12]
    today = today or dt.date.today()
    fields: list[Json] = []
    counts = {"match": 0, "warning": 0, "mismatch": 0}
    for check in read_checks(checks, cfg):
        # the base is parsed once for all its candidates
        base = parse_safely(check["type"], check["kind"], check["base"], cfg, "base", today)
        comparisons = []
        for candidate in check["candidates"]:
            outcome = compare_safely(check["type"], check["kind"], base, candidate["value"], cfg, today)
            comparison = build_result(candidate["source"], candidate["id"], show(check["base"]),
                                      show(candidate["value"]), outcome, cfg)  # fmt: skip
            counts[comparison["status"]] += 1
            comparisons.append(comparison)
        fields.append({"field": check["field"], "type": check["type"],
                       **({"kind": check["kind"]} if check["kind"] else {}),
                       "base": {"raw": show(check["base"]), "normalized": base.get("normalized")},
                       **roll_up(comparisons), "comparisons": comparisons})  # fmt: skip
    log.info("verified request_id=%s checks=%d %s config=%s", request_id, len(fields), counts, cfg["config_hash"])
    return {"config_hash": cfg["config_hash"], "config_label": cfg["config_label"],
            "mode": "fuzzy", "request_id": request_id, "overall": {**roll_up(fields), "counts": counts},
            "fields": fields}  # fmt: skip


def create_verifier(
    config: Mapping[str, Any] | None = None, *, config_path: str | os.PathLike[str] | None = None
) -> Any:
    """Load the settings once and return verify(checks, *, request_id=None, today=None).

    Pass a config mapping (for tests) or a config_path. Otherwise $CROSS_VERIFY_CONFIG_PATH,
    or the file next to this module, is used. Create it once; it is safe to share between threads.
    """
    cfg = prepare_config(config) if config is not None else load_config(config_path)
    mode = cfg["mode"]
    if mode == "fuzzy":
        engine = run_checks  # the rules in this file
    elif mode == "hybrid":
        # Future: run the fuzzy rules first, then let the LLM review the result. Set `engine` here.
        raise ModeNotImplementedError("mode 'hybrid' is not developed yet; use 'fuzzy'")
    elif mode == "llm":
        # Future: the LLM (AWS Bedrock) makes the whole comparison. Set `engine` here.
        raise ModeNotImplementedError("mode 'llm' is not developed yet; use 'fuzzy'")
    else:
        raise ModeNotImplementedError(f"mode '{mode}' has no engine yet; use 'fuzzy'")

    def verify(checks: Any, *, request_id: str | None = None, today: dt.date | None = None) -> Json:
        return engine(checks, cfg, request_id, today)

    return verify


# =============================================================================
# 13. Command line (demo):  python cross_verify.py --input checks.json
# =============================================================================
def read_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Read KEY=value lines. Blank lines and # comments are skipped."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-verify values from several documents.")
    parser.add_argument("--input", "-i", required=True, help="JSON file with the checks, or - for stdin")
    parser.add_argument("--config", help=f"config file (default: ${ENV_CONFIG_PATH}, else {DEFAULT_CONFIG_NAME})")
    parser.add_argument("--env-file", default=".env", help="KEY=value settings file (default: .env)")
    parser.add_argument("--compact", action="store_true", help="print one line of JSON")
    args = parser.parse_args(argv)
    if Path(args.env_file).is_file():
        for key, value in read_env_file(args.env_file).items():
            os.environ.setdefault(key, value)
    logging.basicConfig(level=os.environ.get("CROSS_VERIFY_LOG_LEVEL", "INFO").upper(), stream=sys.stderr)
    try:
        source = sys.stdin if args.input == "-" else open(args.input, encoding="utf-8")  # noqa: SIM115
        with source:
            report = create_verifier(config_path=args.config)(json.load(source))
    except (CrossVerifyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
