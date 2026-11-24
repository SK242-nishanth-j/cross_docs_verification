"""
File: sources.py
Purpose: The people of a case (check order) and the sources of a value (lead, document, bureau).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from src.adapters.kyc.models import BureauReport
from src.adapters.kyc.models import PartyContext
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.ai.agents.anomaly_detection.schemas import DocumentExtraction
from src.services.models import APPLICANT
from src.services.models import ApplicantLead
from src.services.models import CoApplicantLead

DOC_LABEL = {
    "PAN": "PAN",
    "AADHAAR": "Aadhaar",
    "PASSPORT": "Passport",
    "VOTER_ID": "Voter ID",
    "DRIVING_LICENCE": "Driving licence",
    "MARKSHEET": "Marksheet",
    "DEGREE_CERTIFICATE": "Degree certificate",
    "ADMIT_LETTER": "Admit letter",
    "OTHER": "Other",
}
APPLICANT_SIDE = "applicant_side"
_ORDER = {"father": 1, "mother": 2}


@dataclass
class Party:
    """One person of the case: lead details plus the documents read for them."""

    party_id: str
    role: str  # applicant | co_applicant
    relationship: str | None  # relationship to the applicant (None for the applicant)
    lead: ApplicantLead | CoApplicantLead
    extractions: list[DocumentExtraction] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Return the name from the lead.

        Returns:
            The person's name.
        """
        return self.lead.name

    @property
    def label(self) -> str:
        """Return a short label such as ``Applicant`` or ``Father (co_applicant_1)``.

        Returns:
            The label.
        """
        if self.role == "applicant":
            return "Applicant"
        return f"{(self.relationship or 'other').title()} ({self.party_id})"

    def readable(self) -> list[DocumentExtraction]:
        """Return the documents whose extraction succeeded.

        Returns:
            Successful extractions only.
        """
        return [e for e in self.extractions if e.status == "ok"]

    def lead_path(self, attr: str) -> str:
        """Return where a lead value lives, for citations.

        Args:
            attr: Lead attribute, for example ``dob``.

        Returns:
            For example ``lead.co_applicants[co_applicant_1].dob``.
        """
        if self.party_id == APPLICANT:
            return f"lead.applicant.{attr}"
        return f"lead.co_applicants[{self.party_id}].{attr}"


def resolve_parties(case: CaseInput) -> list[Party]:
    """Build the people in check order: applicant, father, mother, then the others.

    Args:
        case: The case input.

    Returns:
        The parties, without documents yet.
    """
    parties = [Party(APPLICANT, "applicant", None, case.lead.applicant)]
    ordered = sorted(
        case.lead.co_applicants,
        key=lambda c: (_ORDER.get(c.relationship, 3), c.party_id),
    )
    return parties + [
        Party(c.party_id, "co_applicant", c.relationship, c) for c in ordered
    ]


def attach_extractions(
    parties: list[Party], extractions: list[DocumentExtraction]
) -> None:
    """Give every party the documents read for it.

    Args:
        parties: The parties.
        extractions: Extraction of every document.
    """
    by_id = {p.party_id: p for p in parties}
    for extraction in extractions:
        by_id[extraction.party_id].extractions.append(extraction)


def party_context(party: Party, case: CaseInput) -> PartyContext:
    """Return what the third-party provider is told about a party.

    Args:
        party: The party.
        case: The case input (for the mock overrides).

    Returns:
        The provider context.
    """
    lead = party.lead
    return PartyContext(
        party_id=party.party_id,
        name=lead.name,
        dob=lead.dob,
        address=lead.address,
        email=lead.email,
        pan=lead.pan,
        override=case.mock_overrides.get(party.party_id),
    )


@dataclass
class Src:
    """One source of a value: the lead, a document or the bureau."""

    key: str
    kind: str  # lead | document | bureau
    label: str
    value: str
    party_id: str
    side: str
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the source for the report.

        Returns:
            Key, kind, label, value, party and citation details.
        """
        return {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "value": self.value,
            "party_id": self.party_id,
            "side": self.side,
            **self.meta,
        }


@dataclass(frozen=True)
class DocRead:
    """Which documents of which party give a value to a group (used by the LLM mode)."""

    party_id: str
    attr: str
    doc_types: frozenset[str] | None
    side: str
    who: str | None


@dataclass
class Group:
    """One field compared across every source that has it."""

    group_id: str
    party_id: str
    check: str
    field_type: str  # cross_verify type
    title: str
    sources: list[Src]
    # Pairs whose two sources both have a side in this set are skipped
    # (they were already compared in the applicant section).
    skip_sides: frozenset[str] = frozenset()
    doc_reads: list[DocRead] = field(default_factory=list)

    def pairs(self) -> list[tuple[int, int]]:
        """Return the source pairs to compare.

        Returns:
            (i, j) index pairs with i < j, without pairs already compared elsewhere.
        """
        out = []
        for i in range(len(self.sources)):
            for j in range(i + 1, len(self.sources)):
                a, b = self.sources[i].side, self.sources[j].side
                if not (a in self.skip_sides and b in self.skip_sides):
                    out.append((i, j))
        return out


def doc_source(
    e: DocumentExtraction, value: str, side: str = "self", who: str | None = None
) -> Src:
    """Return the source of a value read from one document.

    Args:
        e: The document's extraction.
        value: The value.
        side: Side tag used to skip pairs.
        who: Text appended to the label, for example ``applicant's father``.

    Returns:
        The source (its key is set later).
    """
    label = f"{DOC_LABEL.get(e.doc_type, e.doc_type)} · {e.file_name}"
    label += f" · {who}" if who else ""
    meta = {
        "file_name": e.file_name,
        "doc_type": e.doc_type,
        "document_index": e.document_index,
    }
    return Src("", "document", label, value, e.party_id, side, meta)


class SourceBuilder:
    """Collects the sources of one group and numbers them s0, s1, ..."""

    def __init__(self) -> None:
        self.items: list[Src] = []
        self.doc_reads: list[DocRead] = []

    def lead(
        self,
        party: Party,
        attr: str,
        value: str | None,
        side: str = "self",
        who: str | None = None,
    ) -> "SourceBuilder":
        """Add a lead value.

        Args:
            party: Whose lead value it is.
            attr: Lead attribute, for example ``father_name``.
            value: The value; nothing is added when it is empty.
            side: Side tag used to skip pairs.
            who: Label override, for example ``Applicant``.

        Returns:
            The builder, for chaining.
        """
        if value:
            label = f"Lead · {who or party.label} · {attr.replace('_', ' ')}"
            meta = {"path": party.lead_path(attr)}
            self.items.append(Src("", "lead", label, value, party.party_id, side, meta))
        return self

    def docs(
        self,
        party: Party,
        attr: str,
        doc_types: set[str] | None = None,
        side: str = "self",
        who: str | None = None,
    ) -> "SourceBuilder":
        """Add the value ``attr`` of every readable document of a party.

        Args:
            party: Whose documents.
            attr: Extracted field, for example ``dob``.
            doc_types: Only these document types; None for all.
            side: Side tag used to skip pairs.
            who: Text appended to the label, for example ``applicant's father``.

        Returns:
            The builder, for chaining.
        """
        types = frozenset(doc_types) if doc_types is not None else None
        self.doc_reads.append(DocRead(party.party_id, attr, types, side, who))
        for e in party.readable():
            value = e.get(attr)
            if value and (types is None or e.doc_type in types):
                self.items.append(doc_source(e, value, side, who))
        return self

    def bureau(
        self, party: Party, report: BureauReport | None, attr: str
    ) -> "SourceBuilder":
        """Add a bureau value.

        Args:
            party: Whose bureau report.
            report: The bureau report, or None.
            attr: ``name`` or ``dob``.

        Returns:
            The builder, for chaining.
        """
        value = getattr(report, attr, None) if report else None
        if report and value:
            label = f"Bureau ({report.provider}) · {party.label}"
            meta = {"provider": report.provider, "field": attr}
            self.items.append(
                Src("", "bureau", label, value, party.party_id, "self", meta)
            )
        return self

    def build(self) -> list[Src]:
        """Number the sources s0, s1, ... and return them.

        Returns:
            The sources in the order they were added.
        """
        for n, src in enumerate(self.items):
            src.key = f"s{n}"
        return self.items
