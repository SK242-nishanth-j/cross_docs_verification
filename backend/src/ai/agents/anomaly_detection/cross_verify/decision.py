"""
File: decision.py
Purpose: Turn reason codes into a colour and build the per-comparison result.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

from collections.abc import Sequence

from .constants import FLAG_OF_SEVERITY
from .constants import FLAG_RANK
from .constants import REASONS
from .constants import STATUS_OF_FLAG
from .constants import Json
from .text import add_reason
from .text import build_segments


def decide(outcome: Json, cfg: Json) -> Json:
    """The colour is the worst severity among the reasons. Nothing else decides it.

    Args:
        outcome: The outcome of a compare function.
        cfg: Prepared configuration.

    Returns:
        ``{"flag": colour, "reasons": reasons}``; never green unless provably equal.
    """
    reasons: list[Json] = list(outcome["reasons"])
    flag = max(
        (FLAG_OF_SEVERITY[r["severity"]] for r in reasons),
        key=FLAG_RANK.__getitem__,
        default="green",
    )
    if (
        flag == "green"
        and not outcome["exact"]
        and all(REASONS[r["code"]] == "info" for r in reasons)
    ):
        add_reason(
            reasons,
            cfg,
            "DIFFERENCE_UNCLASSIFIED",
            "The values differ in a way that is not classified.",
        )
        flag = (
            "yellow"  # safety net: never green when the values are not provably equal
        )
    return {"flag": flag, "reasons": reasons}


def build_result(
    source: str,
    source_id: str,
    base_raw: str | None,
    cand_raw: str | None,
    outcome: Json,
    cfg: Json,
) -> Json:
    """One comparison, in the shape the frontend receives.

    Args:
        source: Candidate source name.
        source_id: Unique candidate id within the check.
        base_raw: Base value as shown.
        cand_raw: Candidate value as shown.
        outcome: The outcome of a compare function.
        cfg: Prepared configuration.

    Returns:
        Status, colour, reasons and highlight segments of the comparison.
    """
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
        "reasons": [
            {k: r[k] for k in ("code", "severity", "message")}
            for r in decision["reasons"]
        ],
        "fuzzy": {"flag": flag},
        "highlight": {
            "base": build_segments(base_raw, outcome["base_spans"])
            if base_raw is not None
            else [],
            "candidate": build_segments(cand_raw, outcome["cand_spans"])
            if cand_raw is not None
            else [],
        },
    }
    if outcome.get("components"):  # dob and address: a part-by-part table for the UI
        result["components"] = outcome["components"]
    return result


def roll_up(items: Sequence[Json]) -> Json:
    """The worst comparison speaks for the whole group.

    Args:
        items: Comparison or field results with a colour.

    Returns:
        Status, colour and needs_review of the group.
    """
    worst = max(items, key=lambda x: FLAG_RANK[x["color"]])
    return {
        "status": worst["status"],
        "color": worst["color"],
        "needs_review": any(i["needs_review"] for i in items),
    }
