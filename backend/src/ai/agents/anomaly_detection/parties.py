"""
File: parties.py
Purpose: Parties of a case in check order (applicant, father, mother, others) with their documents.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from dataclasses import dataclass
from dataclasses import field

from src.adapters.kyc.models import PartyContext
from src.ai.agents.anomaly_detection.extraction import DocumentExtraction
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.services.models import APPLICANT
from src.services.models import ApplicantLead
from src.services.models import CoApplicantLead

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
            The party's name.
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


def resolve_parties(
    case: CaseInput, extractions: list[DocumentExtraction]
) -> list[Party]:
    """Build the parties in check order and attach their documents.

    Args:
        case: The case input.
        extractions: Extraction of every document.

    Returns:
        Applicant first, then the father, the mother and the other co-applicants.
    """
    parties = [Party(APPLICANT, "applicant", None, case.lead.applicant)]
    ordered = sorted(
        case.lead.co_applicants,
        key=lambda c: (_ORDER.get(c.relationship, 3), c.party_id),
    )
    parties += [Party(c.party_id, "co_applicant", c.relationship, c) for c in ordered]
    by_id = {p.party_id: p for p in parties}
    for extraction in extractions:
        by_id[extraction.party_id].extractions.append(extraction)
    return parties


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
