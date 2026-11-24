"""
File: comparison.py
Purpose: One finding shape for every check, and cross_verify on every pair of sources of every group.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import datetime as dt
from collections.abc import Callable
from typing import Any

from src.ai.agents.anomaly_detection.sources import Group

Finding = dict[str, Any]
Verify = Callable[..., dict[str, Any]]

STATUS_COLOR = {
    "match": "green",
    "warning": "yellow",
    "mismatch": "red",
    "not_evaluated": "grey",
}
COLOR_STATUS = {v: k for k, v in STATUS_COLOR.items()}
# grey (could not be checked) needs a person, so it ranks above green but below yellow
COLOR_RANK = {"green": 0, "grey": 1, "yellow": 2, "red": 3}
_MAX_LISTED = 6


def worst_color(colors: list[str]) -> str:
    """Return the most serious colour.

    Args:
        colors: Colours of several results.

    Returns:
        red > yellow > grey > green; green for an empty list.
    """
    return max(colors, key=COLOR_RANK.__getitem__, default="green")


def finding(
    *,
    check_id: str,
    party_id: str,
    category: str,
    check: str,
    title: str,
    status: str,
    severity: str | None,
    message: str = "",
    mitigant: str | None = None,
    base: dict[str, Any] | None = None,
    comparisons: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
    sanction_condition: str | None = None,
    cm_justification_required: bool = False,
    critical: bool = False,
) -> Finding:
    """Build one check result.

    Args:
        check_id: Unique ID, for example ``applicant.NAME``.
        party_id: The person checked.
        category: ``cross_verification`` or ``third_party``.
        check: Check name, for example ``NAME`` or ``FACE_MATCH``.
        title: Human-readable title.
        status: ``match``, ``warning``, ``mismatch`` or ``not_evaluated``.
        severity: High, Medium or Low.
        message: What was found.
        mitigant: Suggested next step; dropped when the check passed.
        base: The base value and where it came from.
        comparisons: Per-source comparisons (third-party checks).
        evidence: Raw (mock) API answer and other details.
        sanction_condition: Condition to add to the sanction, if any.
        cm_justification_required: Whether the CM must justify it.
        critical: Whether a failure is critical.

    Returns:
        The result dictionary.
    """
    color = STATUS_COLOR[status]
    return {
        "check_id": check_id,
        "party_id": party_id,
        "category": category,
        "check": check,
        "title": title,
        "severity": severity,
        "status": status,
        "color": color,
        "critical": critical and color != "green",
        "message": message,
        "mitigant": mitigant if color != "green" else None,
        "sanction_condition": sanction_condition,
        "cm_justification_required": cm_justification_required,
        "base": base,
        "comparisons": comparisons or [],
        "evidence": evidence or {},
    }


def run_cross_verify(
    verify: Verify, checks: list[dict[str, Any]], today: dt.date, limit: int
) -> dict[str, Any]:
    """Call cross_verify in chunks of ``limit`` checks.

    Args:
        verify: The cross_verify verify function.
        checks: cross_verify checks.
        today: Reference date.
        limit: Largest number of checks per call (config ``limits.max_checks``).

    Returns:
        ``{"fields": {field: field_result}, "engine": engine_info}``.
    """
    by_field: dict[str, Any] = {}
    info: dict[str, Any] = {"engine": "cross_verify", "checks_sent": len(checks)}
    for start in range(0, len(checks), limit):
        report = verify(checks[start : start + limit], today=today)
        info.update(mode=report.get("mode"), config_label=report.get("config_label"))
        by_field.update({f["field"]: f for f in report["fields"]})
    return {"fields": by_field, "engine": info}


def _checks_of(group: Group) -> list[dict[str, Any]]:
    """cross_verify checks for every allowed pair of a group (each source is base once)."""
    allowed = set(group.pairs())
    checks = []
    for i, base in enumerate(group.sources):
        cands = [
            group.sources[j]
            for j in range(i + 1, len(group.sources))
            if (i, j) in allowed
        ]
        if cands:
            checks.append(
                {
                    "field": f"{group.group_id}|{i}",
                    "type": group.field_type,
                    "base": base.value,
                    "candidates": [{"source": c.key, "value": c.value} for c in cands],
                }
            )
    return checks


def _pairs_of(group: Group, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect the pair results of a group from the cross_verify answer."""
    pairs = []
    for i, base in enumerate(group.sources):
        result = fields.get(f"{group.group_id}|{i}")
        for comp in result["comparisons"] if result else []:
            pairs.append(
                {
                    "a": base.key,
                    "b": comp["source"],
                    "status": comp["status"],
                    "color": comp["color"],
                    "reasons": comp["reasons"],
                    "highlight": {
                        "a": comp["highlight"]["base"],
                        "b": comp["highlight"]["candidate"],
                    },
                }
            )
    return pairs


def _summary(group: Group, pairs: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    """Explain the group result and count, per source, the pairs it differs in."""
    labels = {s.key: s.label for s in group.sources}
    bad = [p for p in pairs if p["color"] != "green"]
    per_source = []
    for s in group.sources:
        mine = [p for p in pairs if s.key in (p["a"], p["b"])]
        per_source.append(
            {
                "key": s.key,
                "label": s.label,
                "pairs": len(mine),
                "differs_in": sum(1 for p in mine if p["color"] != "green"),
                "worst_color": worst_color([p["color"] for p in mine]),
            }
        )
    if not bad:
        return (
            f"All {len(group.sources)} sources agree ({len(pairs)} pair(s) compared).",
            per_source,
        )
    parts = []
    for p in bad[:_MAX_LISTED]:
        why = "; ".join(r["message"] for r in p["reasons"] if r["severity"] != "info")
        parts.append(f"{labels[p['a']]} vs {labels[p['b']]}: {why or p['status']}")
    more = f" (+{len(bad) - _MAX_LISTED} more)" if len(bad) > _MAX_LISTED else ""
    message = f"{len(bad)} of {len(pairs)} pair(s) differ. " + " | ".join(parts) + more
    odd = [s for s in per_source if s["differs_in"] == len(bad) == s["pairs"]]
    if len(odd) == 1 and len(group.sources) > 2:
        message = f"Odd one out: {odd[0]['label']}. " + message
    return message, per_source


def group_finding(
    group: Group, pairs: list[dict[str, Any]], config: dict[str, Any]
) -> Finding:
    """Turn the compared pairs of one group into its finding.

    Args:
        group: The group.
        pairs: Pair results (from cross_verify or from the LLM).
        config: The anomaly configuration (severity and mitigant of each check).

    Returns:
        The finding with its sources, pairs and per-source counts.
    """
    meta = config["checks"][group.check]
    color = worst_color([p["color"] for p in pairs])
    message, per_source = _summary(group, pairs)
    result = finding(
        check_id=group.group_id,
        party_id=group.party_id,
        category="cross_verification",
        check=group.check,
        title=group.title,
        status=COLOR_STATUS[color],
        severity=meta["severity"],
        message=message,
        mitigant=meta.get("mitigant"),
    )
    result["sources"] = [s.as_dict() for s in group.sources]
    result["pairs"] = sorted(pairs, key=lambda p: -COLOR_RANK[p["color"]])
    result["per_source"] = per_source
    return result


def not_compared(groups: list[Group]) -> list[dict[str, Any]]:
    """Return the groups with fewer than two sources (nothing to compare).

    Args:
        groups: All groups.

    Returns:
        One entry per group with zero or one source.
    """
    return [
        {
            "check_id": g.group_id,
            "party_id": g.party_id,
            "check": g.check,
            "title": g.title,
            "sources": [s.as_dict() for s in g.sources],
        }
        for g in groups
        if len(g.sources) < 2
    ]


def evaluate_groups(
    groups: list[Group],
    verify: Verify,
    config: dict[str, Any],
    today: dt.date,
    limit: int,
) -> tuple[list[Finding], dict[str, Any]]:
    """Compare every pair of every group with cross_verify.

    Args:
        groups: The comparison groups.
        verify: The cross_verify verify function.
        config: The anomaly configuration.
        today: Reference date.
        limit: Largest number of checks per cross_verify call.

    Returns:
        (findings of the groups with two or more sources, cross_verify engine info).
    """
    runnable = [g for g in groups if len(g.sources) >= 2]
    checks = [c for g in runnable for c in _checks_of(g)]
    run: dict[str, Any] = (
        run_cross_verify(verify, checks, today, limit)
        if checks
        else {"fields": {}, "engine": {"engine": "cross_verify", "checks_sent": 0}}
    )
    findings = []
    for g in runnable:
        pairs = _pairs_of(g, run["fields"])
        if pairs:
            findings.append(group_finding(g, pairs, config))
    return findings, run["engine"]
