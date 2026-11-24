"""
File: amounts.py
Purpose: Parse and compare money amounts.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

import datetime as dt
import re

from .constants import Json
from .constants import Span
from .text import add_reason
from .text import ascii_digits
from .text import failure
from .text import fold
from .text import make_outcome

# "Rs. 12,50,000/-", "1250000", "12.5 lakh" and "INR 1250000.00" are the same amount. Currencies are never
# converted: two different currencies are a mismatch, because a rate belongs to the caller, not here.
_AMOUNT_NUMBER = re.compile(r"-?\d+(?:,\d+)*(?:\.\d+)?")


def parse_amount(text: str, cfg: Json, side: str) -> Json:
    """Read one amount and, when it is printed, its currency.

    Args:
        text: Raw amount text.
        cfg: Prepared configuration.
        side: "base" or "candidate", used in reason messages.

    Returns:
        The parsed amount ({"ok": True, ...}) or a failure ({"ok": False, ...}).
    """
    rt = cfg["_rt"]
    reasons: list[Json] = []
    ignored: list[Span] = []
    body = ascii_digits(text)
    start = 0
    label = rt["amount_label"].match(body)
    if label and label.end() < len(body):
        ignored.append((0, label.end(), "ignored"))
        start = label.end()
        add_reason(
            reasons,
            cfg,
            "LABEL_STRIPPED",
            f"A label was removed from the {side} amount.",
        )
    number = _AMOUNT_NUMBER.search(body, start)
    if number is None:
        return failure("UNPARSEABLE", f"No amount could be read from the {side} value.")
    value = float(number.group().replace(",", ""))
    scale = rt["scale_after"].match(body, number.end())  # "12.5 lakh", "₹5 cr"
    if scale is not None:
        value *= rt["scales"][fold(scale.group().strip(" -"))]
    found = rt["currency"].search(body)
    currency = rt["currencies"][fold(found.group())] if found is not None else None
    return {
        "ok": True,
        "raw": text,
        "value": value,
        "currency": currency,
        "span": (number.start(), scale.end() if scale is not None else number.end()),
        "ignored": ignored,
        "reasons": reasons,
        "normalized": f"{currency} {value:,.2f}" if currency else f"{value:,.2f}",
    }


def compare_amounts(base: Json, cand: Json, cfg: Json, today: dt.date) -> Json:
    """Compare two amounts.

    A rounding or near difference is a warning, a real difference is a mismatch.

    Args:
        base: Parsed base amount.
        cand: Parsed candidate amount.
        cfg: Prepared configuration.
        today: Reference date (unused; all compare functions share one signature).

    Returns:
        The outcome with reasons and highlight spans.
    """
    ac = cfg["amount"]
    reasons = [*base["reasons"], *cand["reasons"]]
    money_b, money_c = base["currency"], cand["currency"]
    clashing = bool(money_b and money_c and money_b != money_c)
    assumed = bool(
        (money_b or money_c)
        and not (money_b and money_c)
        and (money_b or money_c) != ac["default_currency"]
    )
    if clashing:
        add_reason(
            reasons,
            cfg,
            "CURRENCY_MISMATCH",
            f"The amounts are in different currencies ({money_b} and {money_c}).",
        )
    elif assumed:
        add_reason(
            reasons,
            cfg,
            "CURRENCY_ASSUMED",
            f"Only one side names a currency ({money_b or money_c}); the other was read as the same.",
        )

    gap = abs(base["value"] - cand["value"])
    largest = max(abs(base["value"]), abs(cand["value"]))
    if gap == 0 and clashing:
        pass  # the numbers agree but the money does not, which the currency reason already says
    elif gap == 0:
        code = (
            "EXACT"
            if base["raw"].strip() == cand["raw"].strip()
            else "NORMALIZED_EQUAL"
        )
        add_reason(reasons, cfg, code, "The amounts are the same.")
    elif gap <= ac["round_tolerance"]:
        add_reason(
            reasons,
            cfg,
            "AMOUNT_ROUNDED",
            f"The amounts differ by {gap:,.2f}, which is rounding.",
        )
    elif largest and 100.0 * gap / largest <= ac["near_percent"]:
        add_reason(
            reasons,
            cfg,
            "AMOUNT_NEAR",
            f"The amounts differ by {gap:,.2f} ({100.0 * gap / largest:.2f} percent).",
        )
    else:
        add_reason(
            reasons, cfg, "AMOUNT_DIFFERENT", f"The amounts differ by {gap:,.2f}."
        )

    out = make_outcome(reasons, gap == 0 and not (clashing or assumed), base, cand)
    mark = "match" if gap == 0 else "conflict"
    out["base_spans"].append((*base["span"], mark))
    out["cand_spans"].append((*cand["span"], mark))
    money = "conflict" if clashing else "match"
    out["components"] = [
        {
            "component": "value",
            "base": base["value"],
            "candidate": cand["value"],
            "relation": mark,
        },
        {
            "component": "currency",
            "base": money_b,
            "candidate": money_c,
            "relation": money,
        },
    ]
    return out
