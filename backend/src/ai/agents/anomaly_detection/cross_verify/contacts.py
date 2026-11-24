"""
File: contacts.py
Purpose: Parse and compare email addresses and phone numbers.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt
import re

from rapidfuzz.distance import OSA

from .constants import Json
from .constants import Span
from .text import add_reason
from .text import ascii_digits
from .text import failure
from .text import fold
from .text import make_outcome

_EMAIL = re.compile(r"[^@\s,;<>()]+@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}")


def parse_email(text: str, cfg: Json, side: str) -> Json:
    """Read one email address and work out which mailbox it stands for.

    Args:
        text: Raw email text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.

    Returns:
        The parsed address ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt, ec = cfg["_rt"], cfg["email"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start = 0
    label = rt["email_label"].match(text)
    if label and label.end() < len(text):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(
            reasons,
            cfg,
            "LABEL_STRIPPED",
            f"A label was removed from the {side} email address.",
        )
    found = _EMAIL.search(text, start)
    if found is None:
        return failure(
            "UNPARSEABLE", f"No email address could be read from the {side} value."
        )
    local, _, domain = fold(found.group()).partition("@")
    mailbox = local.partition("+")[0] if ec["ignore_tags"] else local
    if domain in rt["email_dot_domains"]:  # gmail ignores dots inside the name
        mailbox = mailbox.replace(".", "")
    return {
        "ok": True,
        "raw": text,
        "local": local,
        "domain": domain,
        "mailbox": f"{mailbox}@{domain}",
        "span": (found.start(), found.end()),
        "ignored": ignored,
        "reasons": reasons,
        "normalized": f"{local}@{domain}",
    }


def compare_emails(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two email addresses. The same mailbox written differently is a warning.

    Args:
        base: Parsed base email.
        cand: Parsed candidate email.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons and highlight spans.
    """
    reasons = [*base["reasons"], *cand["reasons"]]
    same = base["normalized"] == cand["normalized"]
    if same:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The email addresses are the same.")
        kind = "match"
    elif base["mailbox"] == cand["mailbox"]:
        add_reason(
            reasons,
            cfg,
            "EMAIL_ALIAS",
            "The two addresses reach the same mailbox, written differently.",
        )
        kind = "spelling"
    else:
        add_reason(
            reasons, cfg, "EMAIL_DIFFERENT", "The email addresses are different."
        )
        if OSA.distance(base["normalized"], cand["normalized"]) == 1:
            add_reason(
                reasons,
                cfg,
                "POSSIBLE_TYPO",
                "The addresses differ in one character, which may be a typing error.",
            )
        kind = "conflict"
    out = make_outcome(reasons, same, base, cand)
    out["base_spans"].append((*base["span"], kind))
    out["cand_spans"].append((*cand["span"], kind))
    parts = (
        ("name", base["local"], cand["local"]),
        ("domain", base["domain"], cand["domain"]),
    )
    out["components"] = [
        {
            "component": part,
            "base": left,
            "candidate": right,
            "relation": "match" if left == right else "conflict",
        }
        for part, left, right in parts
    ]
    return out


def parse_phone(text: str, cfg: Json, side: str) -> Json:
    """Read one phone number: keep the digits, then take off a country code or a leading zero.

    Args:
        text: Raw phone text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.

    Returns:
        The parsed number ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt, pc = cfg["_rt"], cfg["phone"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    start = 0
    label = rt["phone_label"].match(text)
    if label and label.end() < len(text):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(
            reasons,
            cfg,
            "LABEL_STRIPPED",
            f"A label was removed from the {side} phone number.",
        )
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
    if (
        country is None
        and len(national) == pc["national_length"] + 1
        and national.startswith("0")
    ):
        national = national[1:]  # 0 98765 43210
    if len(national) < pc["min_digits"]:
        return failure(
            "UNPARSEABLE", f"No phone number could be read from the {side} value."
        )
    return {
        "ok": True,
        "raw": text,
        "national": national,
        "country": country,
        "span": (start, len(text)),
        "ignored": ignored,
        "reasons": reasons,
        "normalized": f"+{country} {national}" if country else national,
    }


def compare_phones(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two phone numbers. '+91 98765 43210' and '09876543210' are the same number.

    Args:
        base: Parsed base number.
        cand: Parsed candidate number.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons and highlight spans.
    """
    pc = cfg["phone"]
    tail = pc["min_visible_tail"]
    reasons = [*base["reasons"], *cand["reasons"]]
    b, c = base["national"], cand["national"]
    here, there = base["country"], cand["country"]
    clashing = bool(here and there and here != there)
    assumed = bool(
        (here or there)
        and not (here and there)
        and (here or there) != pc["default_country"]
    )
    if clashing:
        add_reason(
            reasons,
            cfg,
            "PHONE_DIFFERENT",
            f"The country codes differ (+{here} and +{there}).",
        )
    elif assumed:
        add_reason(
            reasons,
            cfg,
            "PHONE_COUNTRY_ASSUMED",
            f"Only one side names a country code (+{here or there}); the other was read as the same.",
        )
    same = False
    if b == c and not clashing:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The phone numbers are the same.")
        same, kind = not assumed, "match"
    elif b == c:
        kind = "conflict"  # the digits agree, the countries do not
    elif min(len(b), len(c)) >= tail and (b.endswith(c) or c.endswith(b)):
        add_reason(
            reasons,
            cfg,
            "PHONE_PARTIAL",
            "One number holds only the last digits of the other.",
        )
        kind = "spelling"
    else:
        add_reason(reasons, cfg, "PHONE_DIFFERENT", "The phone numbers are different.")
        if OSA.distance(b, c) == 1:
            add_reason(
                reasons,
                cfg,
                "POSSIBLE_TYPO",
                "The numbers differ in one digit, which may be a typing error.",
            )
        kind = "conflict"
    out = make_outcome(reasons, same, base, cand)
    out["base_spans"].append((*base["span"], kind))
    out["cand_spans"].append((*cand["span"], kind))
    return out
