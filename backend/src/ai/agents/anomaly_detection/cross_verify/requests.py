"""
File: requests.py
Purpose: Validate and tidy an incoming list of checks.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import FIELD_TYPES
from .constants import TYPE_ALIASES
from .constants import Json
from .errors import InputError


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
