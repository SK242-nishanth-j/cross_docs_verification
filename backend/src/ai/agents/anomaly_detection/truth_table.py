"""
File: truth_table.py
Purpose: The truth table of each person: one row per source, one column per compared field.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

Each cell shows the source's value and how it compares with the column's base (the
first source, usually the lead). The UI renders this JSON as it is.
"""

import re
from typing import Any

FIELD_LABEL = {
    "NAME": "Name",
    "DOB": "Date of birth",
    "FATHER_NAME": "Father name",
    "MOTHER_NAME": "Mother name",
    "ADDRESS": "Address",
    "HOUSEHOLD_ADDRESS": "Household address",
    "PARENT_NAME": "Name (as parent)",
    "PAN": "PAN",
    "AADHAAR": "Aadhaar (last 4)",
    "PASSPORT_NO": "Passport",
    "VOTER_ID": "Voter ID",
    "DL_NO": "Driving licence",
}
MARK = {
    "green": "✓",
    "yellow": "≈",
    "red": "✗",
    "grey": "–",
    "base": "★",
    "masked": "🔒",
    "single": "•",
}
COLOR_WORD = {
    "green": "Match",
    "yellow": "Review",
    "red": "Mismatch",
    "grey": "Not checked",
}
_MASK_TAG = re.compile(r"\{[A-Z][A-Z0-9_]*\}")
_LEAD_ORDER, _DOC_ORDER, _BUREAU_ORDER = 0, 100, 900


def _row_of(src: dict[str, Any], doc_order: dict[str, int]) -> dict[str, Any]:
    """One row per lead person, document file or bureau source."""
    parts = src["label"].split(" · ")
    if src["kind"] == "document":
        index = doc_order.get(src["file_name"], len(doc_order))
        return {
            "key": f"doc:{src['file_name']}",
            "label": src["file_name"],
            "sub": parts[0],
            "order": _DOC_ORDER + index,
        }
    if src["kind"] == "lead":
        who = parts[1] if len(parts) > 1 else src["party_id"]
        return {
            "key": f"lead:{who}",
            "label": f"Lead · {who}",
            "sub": "application form",
            "order": _LEAD_ORDER if who == "Applicant" else _LEAD_ORDER + 1,
        }
    return {
        "key": f"bureau:{src['label']}",
        "label": src["label"],
        "sub": "third party (mock)",
        "order": _BUREAU_ORDER,
    }


def _cell(column: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """What one source shows in one column."""
    value = src["value"]
    sources = column["sources"]
    if _MASK_TAG.search(value):
        color, note = "masked", "Masked by a PII guardrail; not a real value."
    elif column["finding"] is None or len(sources) < 2:
        color, note = "single", "Only source of this field; nothing to compare."
    elif src["key"] == sources[0]["key"]:
        color, note = (
            "base",
            "Base: every other source in this column is compared with it.",
        )
    else:
        base = sources[0]
        pair = next(
            (
                p
                for p in column["finding"].get("pairs", [])
                if {p["a"], p["b"]} == {base["key"], src["key"]}
            ),
            None,
        )
        if pair is None:
            color = "grey"
            note = f"Not compared with {base['label']}"
            if src["side"] == base["side"]:
                note += " (both are the applicant's; compared in the applicant table)"
        else:
            color = pair["color"]
            why = "; ".join(
                r["message"] for r in pair["reasons"] if r["severity"] != "info"
            )
            note = f"{COLOR_WORD[color]} vs {base['label']}" + (
                f": {why}" if why else ""
            )
    return {"value": value, "color": color, "mark": MARK[color], "note": note}


def _short_title(title: str) -> str:
    """Third-party title without the bracketed part, for example "PAN-Aadhaar linkage"."""
    return re.sub(r"\s*\([^)]*\)", "", title).strip()


def party_table(block: dict[str, Any]) -> dict[str, Any]:
    """Build the truth table of one person.

    Args:
        block: The person's block of the report (findings and single-source checks).

    Returns:
        Columns, rows (sorted: lead, documents, bureau), cells keyed
        ``"<row key>|<column id>"`` and the third-party results.
    """
    columns = [
        {
            "id": f["check_id"],
            "label": FIELD_LABEL.get(f["check"], f["title"]),
            "color": f["color"],
            "title": f["title"],
            "finding": f,
            "sources": f.get("sources", []),
        }
        for f in block["cross_verification"]
    ] + [
        {
            "id": n["check_id"],
            "label": FIELD_LABEL.get(n["check"], n["title"]),
            "color": None,
            "title": n["title"],
            "finding": None,
            "sources": n["sources"],
        }
        for n in block["not_compared"]
        if n["sources"]
    ]
    doc_order = {d["file_name"]: i for i, d in enumerate(block["documents"])}
    rows: dict[str, dict[str, Any]] = {}
    cells: dict[str, dict[str, Any]] = {}
    for col in columns:
        for src in col["sources"]:
            row = _row_of(src, doc_order)
            rows.setdefault(row["key"], row)
            cells.setdefault(f"{row['key']}|{col['id']}", _cell(col, src))
    ordered = sorted(rows.values(), key=lambda r: (r["order"], r["label"]))
    return {
        "party_id": block["party_id"],
        "label": block["label"],
        "name": block["name"],
        "status_color": block["status_color"],
        "columns": [
            {k: c[k] for k in ("id", "label", "color", "title")} for c in columns
        ],
        "rows": [
            {
                "key": r["key"],
                "label": r["label"],
                "sub": r["sub"],
                "is_lead": r["key"].startswith("lead:"),
            }
            for r in ordered
        ],
        "cells": cells,
        "third_party": [
            {
                "check_id": f["check_id"],
                "label": _short_title(f["title"]),
                "color": f["color"],
                "message": f["message"],
            }
            for f in block["third_party"]
        ],
    }


def truth_tables(parties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the truth table of every person.

    Args:
        parties: The person blocks of the report.

    Returns:
        One table per person, in check order.
    """
    return [party_table(p) for p in parties]
