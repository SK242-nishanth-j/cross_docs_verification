"""
File: checks.py
Purpose: Read the checks of a request; turn reasons into a colour and a result.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

from .common import FIELD_TYPES
from .common import FLAG_OF_SEVERITY
from .common import FLAG_RANK
from .common import REASONS
from .common import STATUS_OF_FLAG
from .common import TYPE_ALIASES
from .common import Json
from .common import add_reason
from .common import build_segments
from .config import InputError


def _read_candidates(candidates: Any, where: str, cfg: Json) -> list[Json]:
    if isinstance(candidates, Mapping):  # shorthand {"aadhaar": "...", "pan": "..."}
        candidates = [{"source": k, "value": v} for k, v in candidates.items()]
    if not isinstance(candidates, list) or not candidates:
        raise InputError(f"{where}: 'candidates' must be a non-empty list or object")
    if len(candidates) > cfg["limits"]["max_candidates"]:
        raise InputError(
            f"{where}: too many candidates (limit {cfg['limits']['max_candidates']})"
        )
    if not all(
        isinstance(c, Mapping)
        and isinstance(c.get("source"), str)
        and c["source"].strip()
        for c in candidates
    ):
        raise InputError(f"{where}: every candidate needs a 'source' text")
    names = [c["source"].strip() for c in candidates]
    seen: dict[str, int] = {}
    items = []
    for name, candidate in zip(names, candidates, strict=True):
        seen[name] = (
            seen.get(name, 0) + 1
        )  # the same source twice becomes bank#1, bank#2
        unique = f"{name}#{seen[name]}" if names.count(name) > 1 else name
        items.append({"source": name, "id": unique, "value": candidate.get("value")})
    return items


def read_checks(checks: Any, cfg: Json) -> list[Json]:
    """Check the shape of the request and tidy it.

    Args:
        checks: The list of checks (or ``{"checks": [...]}``).
        cfg: Prepared configuration.

    Returns:
        The checks with normalised type, kind and candidates.

    Raises:
        InputError: If the request is malformed.
    """
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
        asked = (
            str(check.get("type", ""))
            .strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )
        field_type, implied = TYPE_ALIASES.get(asked, (asked, ""))
        if field_type not in FIELD_TYPES:
            raise InputError(
                f"{where}: 'type' must be one of {', '.join(FIELD_TYPES)} (or a name for one of them, "
                f"such as pan, aadhaar, mobile, gender)"
            )
        kind = str(check.get("kind", "") or implied).strip().lower().replace(" ", "_")
        if kind and not _known_kind(field_type, kind, cfg):
            raise InputError(
                f"{where}: 'kind' {kind!r} is not configured for type {field_type!r}"
            )
        if not isinstance(check.get("field"), str) or not check["field"].strip():
            raise InputError(f"{where}: 'field' must be a non-empty text")
        if "base" not in check:
            raise InputError(f"{where}: 'base' is required (use null if unknown)")
        clean.append(
            {
                "field": check["field"].strip(),
                "type": field_type,
                "kind": kind,
                "base": check["base"],
                "candidates": _read_candidates(check.get("candidates"), where, cfg),
            }
        )
    return clean


def _known_kind(field_type: str, kind: str, cfg: Json) -> bool:
    """A kind is only accepted when the settings describe it (id patterns, text word lists)."""
    if field_type == "id":
        return kind in cfg["id"]["patterns"]
    if field_type == "text":
        return kind in cfg["text"]["vocabularies"]
    return False


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
