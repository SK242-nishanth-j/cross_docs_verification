"""
File: groups.py
Purpose: Build the comparison groups (one field, every source that has it) in check order.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

Check order:
  1. Applicant   NAME (+bureau) · DOB (+bureau) · FATHER_NAME · MOTHER_NAME · ADDRESS · IDs
  2. Father      PARENT_NAME: applicant's father name (lead + applicant documents) vs the
                 father's own lead name, documents and bureau · DOB · own parents · IDs ·
                 HOUSEHOLD_ADDRESS: father's lead + documents vs applicant's lead + documents
  3. Mother      same as father, with the mother's name
  4. Others      NAME · DOB · FATHER_NAME · MOTHER_NAME · ADDRESS · IDs across their own sources
The lead is one of the sources and is listed first.
"""

import re
from typing import Any

from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection.parties import Party
from src.ai.agents.anomaly_detection.sources import APPLICANT_SIDE
from src.ai.agents.anomaly_detection.sources import Group
from src.ai.agents.anomaly_detection.sources import SourceBuilder


def _looks_like(value: str, pattern: str) -> bool:
    """Tell whether an ID number matches a pattern, ignoring spaces and dashes."""
    return re.fullmatch(pattern, re.sub(r"[\s-]", "", value).upper()) is not None


def _id_groups(p: Party, id_patterns: dict[str, str]) -> list[Group]:
    """PAN, Aadhaar (last 4), passport, driving licence and voter ID groups of one party."""
    gid, lead = p.party_id, p.lead
    groups = [
        Group(
            f"{gid}.PAN",
            gid,
            "PAN",
            "pan",
            "PAN number",
            SourceBuilder()
            .lead(p, "pan", lead.pan)
            .docs(p, "id_number", {"PAN"})
            .build(),
        ),
    ]
    aadhaar = f"XXXX XXXX {lead.aadhaar_last4}" if lead.aadhaar_last4 else None
    sources = (
        SourceBuilder()
        .lead(p, "aadhaar_last4", aadhaar)
        .docs(p, "id_number", {"AADHAAR"})
    )
    groups.append(
        Group(
            f"{gid}.AADHAAR",
            gid,
            "AADHAAR",
            "aadhaar",
            "Aadhaar number (last 4 digits)",
            sources.build(),
        )
    )

    # The form has one "Passport/ DL. No" box: it joins the passport group or the DL group.
    value = lead.passport_or_dl_number
    has_pp = any(e.doc_type == "PASSPORT" for e in p.readable())
    has_dl = any(e.doc_type == "DRIVING_LICENCE" for e in p.readable())
    to_dl = (
        bool(value)
        and has_dl
        and (not has_pp or _looks_like(value or "", id_patterns["driving_licence"]))
    )
    pp = SourceBuilder().lead(p, "passport_or_dl_number", None if to_dl else value)
    groups.append(
        Group(
            f"{gid}.PASSPORT_NO",
            gid,
            "PASSPORT_NO",
            "passport",
            "Passport number",
            pp.docs(p, "id_number", {"PASSPORT"}).build(),
        )
    )
    dl = SourceBuilder().lead(p, "passport_or_dl_number", value if to_dl else None)
    groups.append(
        Group(
            f"{gid}.DL_NO",
            gid,
            "DL_NO",
            "driving_licence",
            "Driving licence number",
            dl.docs(p, "id_number", {"DRIVING_LICENCE"}).build(),
        )
    )
    voter = (
        SourceBuilder()
        .lead(p, "voter_id", lead.voter_id)
        .docs(p, "id_number", {"VOTER_ID"})
    )
    groups.append(
        Group(
            f"{gid}.VOTER_ID",
            gid,
            "VOTER_ID",
            "voter_id",
            "Voter ID (EPIC) number",
            voter.build(),
        )
    )
    return groups


def _applicant_groups(a: Party, rep: BureauReport | None) -> list[Group]:
    """Name, DOB, parents' names and address groups of the applicant."""
    gid = a.party_id
    return [
        Group(
            f"{gid}.NAME",
            gid,
            "NAME",
            "name",
            "Applicant name",
            SourceBuilder()
            .lead(a, "name", a.lead.name)
            .docs(a, "name")
            .bureau(a, rep, "name")
            .build(),
        ),
        Group(
            f"{gid}.DOB",
            gid,
            "DOB",
            "dob",
            "Applicant date of birth",
            SourceBuilder()
            .lead(a, "dob", a.lead.dob)
            .docs(a, "dob")
            .bureau(a, rep, "dob")
            .build(),
        ),
        Group(
            f"{gid}.FATHER_NAME",
            gid,
            "FATHER_NAME",
            "name",
            "Applicant's father name",
            SourceBuilder()
            .lead(a, "father_name", a.lead.father_name)
            .docs(a, "father_name")
            .build(),
        ),
        Group(
            f"{gid}.MOTHER_NAME",
            gid,
            "MOTHER_NAME",
            "name",
            "Applicant's mother name",
            SourceBuilder()
            .lead(a, "mother_name", a.lead.mother_name)
            .docs(a, "mother_name")
            .build(),
        ),
        Group(
            f"{gid}.ADDRESS",
            gid,
            "ADDRESS",
            "address",
            "Applicant address",
            SourceBuilder()
            .lead(a, "address", a.lead.address)
            .docs(a, "address")
            .build(),
        ),
    ]


def _co_applicant_groups(
    p: Party, applicant: Party, rep: BureauReport | None
) -> list[Group]:
    """Name (or parent link), DOB, own parents and address (or household) groups of a co-applicant."""
    gid = p.party_id
    skip = frozenset({APPLICANT_SIDE})
    groups: list[Group] = []
    if p.relationship in ("father", "mother"):
        rel = p.relationship
        attr = f"{rel}_name"
        b = SourceBuilder().lead(
            applicant,
            attr,
            getattr(applicant.lead, attr),
            side=APPLICANT_SIDE,
            who="Applicant",
        )
        b.docs(applicant, attr, side=APPLICANT_SIDE, who=f"applicant's {rel}")
        b.lead(p, "name", p.lead.name).docs(p, "name").bureau(p, rep, "name")
        title = f"{rel.title()} name: applicant's {rel} name vs the {rel}'s own lead, documents and bureau"
        groups.append(
            Group(
                f"{gid}.PARENT_NAME", gid, "PARENT_NAME", "name", title, b.build(), skip
            )
        )
    else:
        b = (
            SourceBuilder()
            .lead(p, "name", p.lead.name)
            .docs(p, "name")
            .bureau(p, rep, "name")
        )
        groups.append(
            Group(f"{gid}.NAME", gid, "NAME", "name", f"{p.label} name", b.build())
        )

    groups += [
        Group(
            f"{gid}.DOB",
            gid,
            "DOB",
            "dob",
            f"{p.label} date of birth",
            SourceBuilder()
            .lead(p, "dob", p.lead.dob)
            .docs(p, "dob")
            .bureau(p, rep, "dob")
            .build(),
        ),
        Group(
            f"{gid}.FATHER_NAME",
            gid,
            "FATHER_NAME",
            "name",
            f"{p.label}'s own father name",
            SourceBuilder()
            .lead(p, "father_name", p.lead.father_name)
            .docs(p, "father_name")
            .build(),
        ),
        Group(
            f"{gid}.MOTHER_NAME",
            gid,
            "MOTHER_NAME",
            "name",
            f"{p.label}'s own mother name",
            SourceBuilder()
            .lead(p, "mother_name", p.lead.mother_name)
            .docs(p, "mother_name")
            .build(),
        ),
    ]

    if p.relationship in ("father", "mother"):
        b = SourceBuilder().lead(
            applicant,
            "address",
            applicant.lead.address,
            side=APPLICANT_SIDE,
            who="Applicant",
        )
        b.docs(applicant, "address", side=APPLICANT_SIDE, who="applicant")
        b.lead(p, "address", p.lead.address).docs(p, "address")
        title = f"Address: {p.relationship}'s lead and documents vs applicant's address (same household)"
        groups.append(
            Group(
                f"{gid}.HOUSEHOLD_ADDRESS",
                gid,
                "HOUSEHOLD_ADDRESS",
                "address",
                title,
                b.build(),
                skip,
            )
        )
    else:
        b = SourceBuilder().lead(p, "address", p.lead.address).docs(p, "address")
        groups.append(
            Group(
                f"{gid}.ADDRESS",
                gid,
                "ADDRESS",
                "address",
                f"{p.label} address",
                b.build(),
            )
        )
    return groups


def build_groups(
    parties: list[Party], bureau: dict[str, BureauReport], rules: dict[str, Any]
) -> list[Group]:
    """Build every comparison group of the case, in check order.

    Args:
        parties: Parties in check order (applicant first).
        bureau: Bureau report of each party.
        rules: The anomaly rules configuration (ID patterns).

    Returns:
        The groups: applicant, father, mother, then the other co-applicants.
    """
    applicant = parties[0]
    id_patterns: dict[str, str] = rules["id_patterns"]
    groups = _applicant_groups(applicant, bureau.get(applicant.party_id))
    groups += _id_groups(applicant, id_patterns)
    for p in parties[1:]:
        groups += _co_applicant_groups(p, applicant, bureau.get(p.party_id))
        groups += _id_groups(p, id_patterns)
    return groups
