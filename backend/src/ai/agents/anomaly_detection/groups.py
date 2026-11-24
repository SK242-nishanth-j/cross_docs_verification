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
The lead is one of the sources and is listed first. Every mode uses these groups:
cross_verify compares their sources, or the LLM is asked to compare them.
"""

import re
from typing import Any

from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection.sources import APPLICANT_SIDE
from src.ai.agents.anomaly_detection.sources import Group
from src.ai.agents.anomaly_detection.sources import Party
from src.ai.agents.anomaly_detection.sources import SourceBuilder

_SKIP_APPLICANT = frozenset({APPLICANT_SIDE})


def _group(
    party: Party,
    check: str,
    field_type: str,
    title: str,
    builder: SourceBuilder,
    skip: frozenset[str] = frozenset(),
) -> Group:
    """Create one group from its builder."""
    gid = party.party_id
    return Group(
        f"{gid}.{check}",
        gid,
        check,
        field_type,
        title,
        builder.build(),
        skip,
        builder.doc_reads,
    )


def _lead_addresses(
    b: SourceBuilder,
    party: Party,
    fields: list[str],
    side: str = "self",
    who: str | None = None,
) -> SourceBuilder:
    """Add the configured lead address fields (current and/or permanent)."""
    for attr in fields:
        b.lead(party, attr, getattr(party.lead, attr, None), side=side, who=who)
    return b


def _looks_like(value: str, pattern: str) -> bool:
    """Tell whether an ID number matches a pattern, ignoring spaces and dashes."""
    return re.fullmatch(pattern, re.sub(r"[\s-]", "", value).upper()) is not None


def _id_groups(p: Party, id_patterns: dict[str, str]) -> list[Group]:
    """PAN, Aadhaar (last 4), passport, driving licence and voter ID groups of one party."""
    lead = p.lead
    aadhaar = f"XXXX XXXX {lead.aadhaar_last4}" if lead.aadhaar_last4 else None
    # The form has one "Passport/ DL. No" box: it joins the passport group or the DL group.
    value = lead.passport_or_dl_number
    has_pp = any(e.doc_type == "PASSPORT" for e in p.readable())
    has_dl = any(e.doc_type == "DRIVING_LICENCE" for e in p.readable())
    to_dl = (
        bool(value)
        and has_dl
        and (not has_pp or _looks_like(value or "", id_patterns["driving_licence"]))
    )
    pp_value, dl_value = (None, value) if to_dl else (value, None)
    return [
        _group(
            p,
            "PAN",
            "pan",
            "PAN number",
            SourceBuilder().lead(p, "pan", lead.pan).docs(p, "id_number", {"PAN"}),
        ),
        _group(
            p,
            "AADHAAR",
            "aadhaar",
            "Aadhaar number (last 4 digits)",
            SourceBuilder()
            .lead(p, "aadhaar_last4", aadhaar)
            .docs(p, "id_number", {"AADHAAR"}),
        ),
        _group(
            p,
            "PASSPORT_NO",
            "passport",
            "Passport number",
            SourceBuilder()
            .lead(p, "passport_or_dl_number", pp_value)
            .docs(p, "id_number", {"PASSPORT"}),
        ),
        _group(
            p,
            "DL_NO",
            "driving_licence",
            "Driving licence number",
            SourceBuilder()
            .lead(p, "passport_or_dl_number", dl_value)
            .docs(p, "id_number", {"DRIVING_LICENCE"}),
        ),
        _group(
            p,
            "VOTER_ID",
            "voter_id",
            "Voter ID (EPIC) number",
            SourceBuilder()
            .lead(p, "voter_id", lead.voter_id)
            .docs(p, "id_number", {"VOTER_ID"}),
        ),
    ]


def _applicant_groups(
    a: Party, rep: BureauReport | None, address_fields: list[str]
) -> list[Group]:
    """Name, DOB, parents' names and address groups of the applicant."""
    return [
        _group(
            a,
            "NAME",
            "name",
            "Applicant name",
            SourceBuilder()
            .lead(a, "name", a.lead.name)
            .docs(a, "name")
            .bureau(a, rep, "name"),
        ),
        _group(
            a,
            "DOB",
            "dob",
            "Applicant date of birth",
            SourceBuilder()
            .lead(a, "dob", a.lead.dob)
            .docs(a, "dob")
            .bureau(a, rep, "dob"),
        ),
        _group(
            a,
            "FATHER_NAME",
            "name",
            "Applicant's father name",
            SourceBuilder()
            .lead(a, "father_name", a.lead.father_name)
            .docs(a, "father_name"),
        ),
        _group(
            a,
            "MOTHER_NAME",
            "name",
            "Applicant's mother name",
            SourceBuilder()
            .lead(a, "mother_name", a.lead.mother_name)
            .docs(a, "mother_name"),
        ),
        _group(
            a,
            "ADDRESS",
            "address",
            "Applicant address",
            _lead_addresses(SourceBuilder(), a, address_fields).docs(a, "address"),
        ),
    ]


def _co_applicant_groups(
    p: Party, applicant: Party, rep: BureauReport | None, address_fields: list[str]
) -> list[Group]:
    """Name (or parent link), DOB, own parents and address (or household) groups."""
    groups: list[Group] = []
    rel = p.relationship
    if rel in ("father", "mother"):
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
        groups.append(_group(p, "PARENT_NAME", "name", title, b, _SKIP_APPLICANT))
    else:
        b = (
            SourceBuilder()
            .lead(p, "name", p.lead.name)
            .docs(p, "name")
            .bureau(p, rep, "name")
        )
        groups.append(_group(p, "NAME", "name", f"{p.label} name", b))

    groups += [
        _group(
            p,
            "DOB",
            "dob",
            f"{p.label} date of birth",
            SourceBuilder()
            .lead(p, "dob", p.lead.dob)
            .docs(p, "dob")
            .bureau(p, rep, "dob"),
        ),
        _group(
            p,
            "FATHER_NAME",
            "name",
            f"{p.label}'s own father name",
            SourceBuilder()
            .lead(p, "father_name", p.lead.father_name)
            .docs(p, "father_name"),
        ),
        _group(
            p,
            "MOTHER_NAME",
            "name",
            f"{p.label}'s own mother name",
            SourceBuilder()
            .lead(p, "mother_name", p.lead.mother_name)
            .docs(p, "mother_name"),
        ),
    ]

    if rel in ("father", "mother"):
        b = _lead_addresses(
            SourceBuilder(), applicant, address_fields, APPLICANT_SIDE, "Applicant"
        )
        b.docs(applicant, "address", side=APPLICANT_SIDE, who="applicant")
        _lead_addresses(b, p, address_fields).docs(p, "address")
        title = f"Address: {rel}'s lead and documents vs applicant's address (same household)"
        groups.append(
            _group(p, "HOUSEHOLD_ADDRESS", "address", title, b, _SKIP_APPLICANT)
        )
    else:
        b = _lead_addresses(SourceBuilder(), p, address_fields).docs(p, "address")
        groups.append(_group(p, "ADDRESS", "address", f"{p.label} address", b))
    return groups


def build_groups(
    parties: list[Party], bureau: dict[str, BureauReport], config: dict[str, Any]
) -> list[Group]:
    """Build every comparison group of the case, in check order.

    Args:
        parties: Parties in check order (applicant first).
        bureau: Bureau report of each party.
        config: The anomaly configuration (ID patterns, lead address fields).

    Returns:
        The groups: applicant, father, mother, then the other co-applicants.
    """
    applicant = parties[0]
    id_patterns: dict[str, str] = config["id_patterns"]
    address_fields: list[str] = list(config.get("lead_address_fields") or ["address"])
    groups = _applicant_groups(
        applicant, bureau.get(applicant.party_id), address_fields
    )
    groups += _id_groups(applicant, id_patterns)
    for p in parties[1:]:
        groups += _co_applicant_groups(
            p, applicant, bureau.get(p.party_id), address_fields
        )
        groups += _id_groups(p, id_patterns)
    return groups
