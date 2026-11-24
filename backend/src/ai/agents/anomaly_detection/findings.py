"""
File: findings.py
Purpose: One result shape for every check (cross-verification and third-party), plus colour helpers.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from typing import Any

Finding = dict[str, Any]

STATUS_COLOR = {
    "match": "green",
    "warning": "yellow",
    "mismatch": "red",
    "not_evaluated": "grey",
}
COLOR_STATUS = {v: k for k, v in STATUS_COLOR.items()}
# grey (could not be checked) needs a person, so it ranks above green but below yellow
COLOR_RANK = {"green": 0, "grey": 1, "yellow": 2, "red": 3}


def finding(
    *,
    check_id: str,
    party_id: str,
    category: str,
    check: str,
    title: str,
    status: str,
    severity: str | None,
    rule_id: str | None = None,
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
        party_id: The party checked.
        category: ``cross_verification`` or ``third_party``.
        check: Check name, for example ``NAME`` or ``FACE_MATCH``.
        title: Human-readable title.
        status: ``match``, ``warning``, ``mismatch`` or ``not_evaluated``.
        severity: High, Medium or Low.
        rule_id: Rule from the rules sheet (KY-01 ...), when there is one.
        message: What was found, without values from other cases.
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
        "rule_id": rule_id,
        "title": title,
        "severity": severity,
        "status": status,
        "color": color,
        "needs_review": color != "green",
        "critical": critical and color != "green",
        "message": message,
        "mitigant": mitigant if color != "green" else None,
        "sanction_condition": sanction_condition,
        "cm_justification_required": cm_justification_required,
        "base": base,
        "comparisons": comparisons or [],
        "evidence": evidence or {},
    }


def worst_color(colors: list[str]) -> str:
    """Return the most serious colour.

    Args:
        colors: Colours of several results.

    Returns:
        red > yellow > grey > green; green for an empty list.
    """
    return max(colors, key=COLOR_RANK.__getitem__, default="green")


def rule_fields(
    party_id: str, rule_id: str, rules: dict[str, Any], check: str
) -> dict[str, Any]:
    """Return the fields every third-party finding of ``rule_id`` shares.

    Args:
        party_id: The party checked.
        rule_id: Rule from the rules sheet, for example ``KY-03``.
        rules: The anomaly rules configuration (titles, severities, mitigants).
        check: Check name, for example ``PAN_AADHAAR_LINK``.

    Returns:
        Keyword arguments for ``finding``: check_id, party_id, category, check,
        rule_id, title, severity and mitigant.
    """
    rule = rules["rules"][rule_id]
    return {
        "check_id": f"{party_id}.{rule_id}",
        "party_id": party_id,
        "category": "third_party",
        "check": check,
        "rule_id": rule_id,
        "title": f"{rule_id} {rule['title']}",
        "severity": rule["severity"],
        "mitigant": rule["mitigant"],
    }
