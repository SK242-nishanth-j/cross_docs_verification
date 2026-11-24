"""
File: pairs.py
Purpose: Compare every pair of sources of every group with cross_verify and turn the answers into findings.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import datetime as dt
from collections.abc import Callable
from typing import Any

from src.ai.agents.anomaly_detection.findings import COLOR_RANK
from src.ai.agents.anomaly_detection.findings import Finding
from src.ai.agents.anomaly_detection.findings import finding
from src.ai.agents.anomaly_detection.findings import worst_color
from src.ai.agents.anomaly_detection.sources import Group

Verify = Callable[..., dict[str, Any]]
_STATUS = {"green": "match", "yellow": "warning", "red": "mismatch"}
_MAX_LISTED = 6


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
        info.update(
            mode=report.get("mode"),
            config_hash=report.get("config_hash"),
            config_label=report.get("config_label"),
        )
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
            pair = {
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
            if "components" in comp:
                pair["components"] = comp["components"]
            pairs.append(pair)
    return pairs


def _summary(
    group: Group, pairs: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
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


def evaluate_groups(
    groups: list[Group],
    verify: Verify,
    rules: dict[str, Any],
    today: dt.date,
    limit: int,
) -> tuple[list[Finding], list[dict[str, Any]], dict[str, Any]]:
    """Compare every pair of every group.

    Args:
        groups: The comparison groups.
        verify: The cross_verify verify function.
        rules: The anomaly rules configuration (severity, rule IDs, mitigants).
        today: Reference date.
        limit: Largest number of checks per cross_verify call.

    Returns:
        (findings, groups with a single source, cross_verify engine info).
    """
    runnable = [g for g in groups if len(g.sources) >= 2]
    checks = [c for g in runnable for c in _checks_of(g)]
    empty: dict[str, Any] = {
        "fields": {},
        "engine": {"engine": "cross_verify", "checks_sent": 0},
    }
    run = run_cross_verify(verify, checks, today, limit) if checks else empty

    findings: list[Finding] = []
    for g in runnable:
        pairs = _pairs_of(g, run["fields"])
        if not pairs:
            continue
        color = worst_color([p["color"] for p in pairs])
        meta = rules["checks"][g.check]
        rule_id = meta.get("rule_id")
        message, per_source = _summary(g, pairs)
        result = finding(
            check_id=g.group_id,
            party_id=g.party_id,
            category="cross_verification",
            check=g.check,
            title=g.title,
            status=_STATUS[color],
            severity=meta["severity"],
            rule_id=rule_id,
            message=message,
            mitigant=meta.get("mitigant")
            or (rules["rules"][rule_id]["mitigant"] if rule_id else None),
        )
        result["sources"] = [s.as_dict() for s in g.sources]
        result["pairs"] = sorted(pairs, key=lambda p: -COLOR_RANK[p["color"]])
        result["per_source"] = per_source
        findings.append(result)

    single = [
        {
            "check_id": g.group_id,
            "party_id": g.party_id,
            "title": g.title,
            "sources": [s.as_dict() for s in g.sources],
        }
        for g in groups
        if len(g.sources) == 1
    ]
    return findings, single, run["engine"]
