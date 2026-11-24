"""
File: report.py
Purpose: Assemble the Anomaly Detection report and the compact summary the orchestrator LLM sees.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import datetime as dt
from typing import Any

from src.ai.agents.anomaly_detection.extraction import DocumentExtraction
from src.ai.agents.anomaly_detection.findings import COLOR_RANK
from src.ai.agents.anomaly_detection.findings import Finding
from src.ai.agents.anomaly_detection.findings import worst_color
from src.ai.agents.anomaly_detection.parties import Party

_SEVERITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
_ANOMALY_KEYS = (
    "check_id",
    "party_id",
    "category",
    "rule_id",
    "title",
    "severity",
    "status",
    "color",
    "critical",
    "message",
    "mitigant",
)
_TOP_ANOMALIES = 15


def _party_block(
    p: Party,
    cross: list[Finding],
    third_party: list[Finding],
    single: list[dict[str, Any]],
) -> dict[str, Any]:
    """Everything the report holds about one party."""
    mine_cross = [f for f in cross if f["party_id"] == p.party_id]
    mine_api = [f for f in third_party if f["party_id"] == p.party_id]
    return {
        "party_id": p.party_id,
        "role": p.role,
        "relationship": p.relationship,
        "name": p.name,
        "label": p.label,
        "status_color": worst_color([f["color"] for f in mine_cross + mine_api]),
        "documents": [
            {"file_name": e.file_name, "doc_type": e.doc_type, "status": e.status}
            for e in p.extractions
        ],
        "cross_verification": mine_cross,
        "third_party": mine_api,
        "not_compared": [n for n in single if n["party_id"] == p.party_id],
    }


def build_report(
    *,
    case_id: str,
    parties: list[Party],
    cross: list[Finding],
    third_party: list[Finding],
    single: list[dict[str, Any]],
    extractions: list[DocumentExtraction],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build the full report of one run.

    Args:
        case_id: The case.
        parties: Parties in check order.
        cross: Cross-verification findings.
        third_party: Third-party findings.
        single: Groups with only one source (nothing to compare).
        extractions: Extraction of every document.
        config: Versions of the configuration, engine, model and provider.

    Returns:
        Summary, anomalies, sanction conditions, CM justifications, per-party
        results and the extraction table.
    """
    findings = [*cross, *third_party]
    counts = dict.fromkeys(COLOR_RANK, 0)
    for f in findings:
        counts[f["color"]] += 1
    anomalies = sorted(
        ({k: f[k] for k in _ANOMALY_KEYS} for f in findings if f["color"] != "green"),
        key=lambda a: (-COLOR_RANK[a["color"]], _SEVERITY_RANK.get(a["severity"], 3)),
    )
    return {
        "agent": "anomaly_detection",
        "case_id": case_id,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "config": config,
        "summary": {
            "overall_color": worst_color([f["color"] for f in findings]),
            "counts": counts,
            "total_checks": len(findings),
            "pairs_compared": sum(len(f.get("pairs", [])) for f in cross),
            "high_severity_flags": sum(
                1
                for a in anomalies
                if a["severity"] == "High" and a["color"] in ("red", "yellow")
            ),
            "critical_flags": sum(1 for a in anomalies if a["critical"]),
        },
        "anomalies": anomalies,
        "sanction_conditions": [
            {
                "party_id": f["party_id"],
                "rule_id": f["rule_id"],
                "condition": f["sanction_condition"],
            }
            for f in findings
            if f["sanction_condition"]
        ],
        "cm_justifications": [
            {"party_id": f["party_id"], "rule_id": f["rule_id"], "reason": f["message"]}
            for f in findings
            if f["cm_justification_required"] and f["color"] != "green"
        ],
        "parties": [_party_block(p, cross, third_party, single) for p in parties],
        "extraction": [e.as_report() for e in extractions],
    }


def compact_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Return the small summary the orchestrator's LLM sees (no document text, no values).

    Args:
        report: The full report.

    Returns:
        Counts, sanction conditions, CM justifications and the top anomalies.
    """
    return {
        "case_id": report["case_id"],
        "summary": report["summary"],
        "sanction_conditions": report["sanction_conditions"],
        "cm_justifications": [
            {"party_id": c["party_id"], "rule_id": c["rule_id"]}
            for c in report["cm_justifications"]
        ],
        "top_anomalies": [
            {
                k: a[k]
                for k in (
                    "party_id",
                    "title",
                    "rule_id",
                    "severity",
                    "color",
                    "critical",
                )
            }
            for a in report["anomalies"][:_TOP_ANOMALIES]
        ],
    }
