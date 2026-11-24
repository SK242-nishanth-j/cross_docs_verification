"""
File: bureau_rules.py
Purpose: KY-02: the lead address must match a bureau address reported in the last 12 months.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import datetime as dt
from typing import Any

from src.adapters.kyc.base import to_jsonable
from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection.findings import COLOR_RANK
from src.ai.agents.anomaly_detection.findings import Finding
from src.ai.agents.anomaly_detection.findings import finding
from src.ai.agents.anomaly_detection.findings import rule_fields
from src.ai.agents.anomaly_detection.pairs import Verify
from src.ai.agents.anomaly_detection.pairs import run_cross_verify
from src.ai.agents.anomaly_detection.parties import Party

_STATUS = {"green": "match", "yellow": "warning", "red": "mismatch"}
_DAYS_PER_MONTH = 30.44


def ky02(
    party: Party,
    report: BureauReport,
    verify: Verify,
    rules: dict[str, Any],
    today: dt.date,
) -> Finding:
    """KY-02: the lead address must match a bureau address reported in the last 12 months.

    Args:
        party: The party.
        report: The party's bureau report.
        verify: The cross_verify verify function.
        rules: The anomaly rules configuration.
        today: Reference date.

    Returns:
        The finding (best match among the recent bureau addresses).
    """
    common = rule_fields(party.party_id, "KY-02", rules, "BUREAU_ADDRESS")
    months = int(rules["kyc_rules"]["bureau_address_window_months"])
    cutoff = today - dt.timedelta(days=round(months * _DAYS_PER_MONTH))
    recent = [a for a in report.addresses if a.reported_on >= cutoff]
    older = [
        {"address": a.address, "reported_on": a.reported_on.isoformat()}
        for a in report.addresses
        if a.reported_on < cutoff
    ]
    evidence = {
        "provider": report.provider,
        "window_months": months,
        "cutoff": cutoff.isoformat(),
        "ignored_older_addresses": older,
        "response": to_jsonable(report.raw),
    }
    address = party.lead.address
    base = {"value": address, "source": party.lead_path("address")}
    if not address:
        return finding(
            **common,
            status="not_evaluated",
            base=base,
            evidence=evidence,
            message="The lead has no address for this party.",
        )
    if not recent:
        return finding(
            **common,
            status="not_evaluated",
            base=base,
            evidence=evidence,
            message=f"The bureau reported no address in the last {months} months.",
        )
    check = {
        "field": "ky02",
        "type": "address",
        "base": address,
        "candidates": [
            {"source": f"b{n}", "value": a.address} for n, a in enumerate(recent)
        ],
    }
    comps = run_cross_verify(verify, [check], today, 1)["fields"]["ky02"]["comparisons"]
    comparisons = [
        {
            "source_kind": "bureau",
            "provider": report.provider,
            "value": a.address,
            "reported_on": a.reported_on.isoformat(),
            "status": c["status"],
            "color": c["color"],
            "reasons": c["reasons"],
            "highlight": c["highlight"],
        }
        for a, c in zip(recent, comps, strict=True)
    ]
    best = min(comparisons, key=lambda c: COLOR_RANK[c["color"]])
    status = _STATUS[best["color"]]
    message = (
        f"The lead address matches a bureau address reported on {best['reported_on']}."
        if status == "match"
        else f"The lead address does not match any bureau address from the last {months} months."
    )
    return finding(
        **common,
        status=status,
        base=base,
        comparisons=comparisons,
        evidence=evidence,
        message=message,
    )
