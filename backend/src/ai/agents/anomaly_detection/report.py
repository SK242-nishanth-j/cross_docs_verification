"""
File: report.py
Purpose: Assemble the report (checklist, per-person results, truth table) and the orchestrator summary.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import datetime as dt
from typing import Any

from src.ai.agents.anomaly_detection.comparison import COLOR_RANK
from src.ai.agents.anomaly_detection.comparison import Finding
from src.ai.agents.anomaly_detection.comparison import worst_color
from src.ai.agents.anomaly_detection.schemas import DocumentExtraction
from src.ai.agents.anomaly_detection.sources import Party
from src.ai.agents.anomaly_detection.truth_table import truth_tables

_SEVERITY_RANK = {"High": 0, "Medium": 1, "Low": 2}
_ANOMALY_KEYS = (
    "check_id",
    "party_id",
    "category",
    "check",
    "title",
    "severity",
    "status",
    "color",
    "critical",
    "message",
    "mitigant",
)
_TOP_ANOMALIES = 15
_COLOR_WORD = {
    "green": "match",
    "yellow": "review",
    "red": "mismatch",
    "grey": "not checked",
}


def _item(label: str, status: str, color: str | None, detail: str) -> dict[str, Any]:
    """One checklist line."""
    return {"item": label, "status": status, "color": color, "detail": detail}


def _bureau_item(
    label: str, cross: list[Finding], third: list[Finding]
) -> dict[str, Any]:
    """Bureau report cross-check: bureau name / DOB pairs and the bureau address."""
    colors = []
    for f in cross:
        bureau_keys = {s["key"] for s in f.get("sources", []) if s["kind"] == "bureau"}
        colors += [
            p["color"] for p in f.get("pairs", []) if {p["a"], p["b"]} & bureau_keys
        ]
    colors += [f["color"] for f in third if f["check"] == "BUREAU_ADDRESS"]
    if not colors:
        return _item(label, "no_data", None, "No bureau value to compare.")
    color = worst_color(colors)
    return _item(label, "done", color, f"Done: {_COLOR_WORD[color]}.")


def checklist(
    cross: list[Finding],
    third: list[Finding],
    single: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build one person's checklist: every configured check, done or not, with its result.

    Args:
        cross: The person's cross-verification findings.
        third: The person's third-party findings.
        single: The person's checks with fewer than two sources.
        config: The anomaly configuration (checklist labels).

    Returns:
        One line per check that applies to this person.
    """
    items = []
    done = {f["check"]: f for f in cross}
    lonely = {s["check"]: s for s in single}
    for check, meta in config["checks"].items():
        if check in done:
            f = done[check]
            items.append(
                _item(
                    meta["label"],
                    "done",
                    f["color"],
                    f"Done: {_COLOR_WORD[f['color']]} ({len(f.get('pairs', []))} pair(s)).",
                )
            )
        elif check in lonely:
            n = len(lonely[check]["sources"])
            detail = "Only one source, nothing to compare." if n else "No value found."
            items.append(
                _item(meta["label"], "one_source" if n else "no_data", None, detail)
            )
    tp = config["third_party"]["checks"]
    items.append(_bureau_item(tp["BUREAU_REPORT"]["label"], cross, third))
    for check, meta in tp.items():
        mine = [f for f in third if f["check"] == check]
        if check == "BUREAU_REPORT" or not mine:
            continue
        color = worst_color([f["color"] for f in mine])
        items.append(
            _item(meta["label"], "done", color, f"Done: {_COLOR_WORD[color]}.")
        )
    return items


def _party_block(
    p: Party,
    cross: list[Finding],
    third_party: list[Finding],
    single: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Everything the report holds about one person."""
    mine_cross = [f for f in cross if f["party_id"] == p.party_id]
    mine_api = [f for f in third_party if f["party_id"] == p.party_id]
    mine_single = [n for n in single if n["party_id"] == p.party_id]
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
        "checklist": checklist(mine_cross, mine_api, mine_single, config),
        "cross_verification": mine_cross,
        "third_party": mine_api,
        "not_compared": mine_single,
    }


def build_report(
    *,
    case_id: str,
    mode: str,
    parties: list[Party],
    cross: list[Finding],
    third_party: list[Finding],
    single: list[dict[str, Any]],
    extractions: list[DocumentExtraction],
    config: dict[str, Any],
    engine: dict[str, Any],
) -> dict[str, Any]:
    """Build the full report of one run.

    Args:
        case_id: The case.
        mode: The pipeline that ran.
        parties: People in check order.
        cross: Cross-verification findings.
        third_party: Third-party findings.
        single: Checks with fewer than two sources.
        extractions: Extraction of every document.
        config: The anomaly configuration.
        engine: Who compared (cross_verify or the LLM), versions and models.

    Returns:
        Summary, checklist, anomalies, per-person results, truth tables and the
        JSON read from every document.
    """
    findings = [*cross, *third_party]
    counts = dict.fromkeys(COLOR_RANK, 0)
    for f in findings:
        counts[f["color"]] += 1
    anomalies = sorted(
        ({k: f[k] for k in _ANOMALY_KEYS} for f in findings if f["color"] != "green"),
        key=lambda a: (-COLOR_RANK[a["color"]], _SEVERITY_RANK.get(a["severity"], 3)),
    )
    blocks = [_party_block(p, cross, third_party, single, config) for p in parties]
    return {
        "agent": "anomaly_detection",
        "case_id": case_id,
        "mode": mode,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "config": engine,
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
                "check": f["check"],
                "condition": f["sanction_condition"],
            }
            for f in findings
            if f["sanction_condition"]
        ],
        "cm_justifications": [
            {"party_id": f["party_id"], "check": f["check"], "reason": f["message"]}
            for f in findings
            if f["cm_justification_required"] and f["color"] != "green"
        ],
        "parties": blocks,
        "truth_table": truth_tables(blocks),
        "extraction": [e.as_report() for e in extractions],
    }


def compact_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Return the small summary the orchestrator's LLM sees (no document values).

    Args:
        report: The full report.

    Returns:
        Counts, sanction conditions, CM justifications and the top anomalies.
    """
    return {
        "case_id": report["case_id"],
        "mode": report["mode"],
        "summary": report["summary"],
        "sanction_conditions": report["sanction_conditions"],
        "cm_justifications": [
            {"party_id": c["party_id"], "check": c["check"]}
            for c in report["cm_justifications"]
        ],
        "top_anomalies": [
            {k: a[k] for k in ("party_id", "title", "severity", "color", "critical")}
            for a in report["anomalies"][:_TOP_ANOMALIES]
        ],
    }
