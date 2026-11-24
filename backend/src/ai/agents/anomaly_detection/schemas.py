"""
File: schemas.py
Purpose: Trigger payload (one OCR JSON per document), the case input and the per-document extraction schema.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic
"""

from typing import Any
from typing import Literal
from typing import get_args

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from src.adapters.kyc.models import PartyMockOverride
from src.services.models import CASE_ID_PATTERN
from src.services.models import Lead

PARTY_ID_PATTERN = r"^(applicant|co_applicant_[1-9][0-9]?)$"

DocType = Literal[
    "PAN",
    "AADHAAR",
    "PASSPORT",
    "VOTER_ID",
    "DRIVING_LICENCE",
    "MARKSHEET",
    "DEGREE_CERTIFICATE",
    "ADMIT_LETTER",
    "OTHER",
]
DOC_TYPES: tuple[str, ...] = get_args(DocType)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentIn(_Strict):
    """One document: who it belongs to, what it is, and its OCR."""

    party_id: str = Field(pattern=PARTY_ID_PATTERN)
    doc_type: DocType
    file_name: str = Field(min_length=1, max_length=255)
    ocr: dict[str, Any] | None = Field(default=None, description="OCR JSON (pages[])")
    raw_ocr: str | None = Field(
        default=None, max_length=300_000, description="or plain text"
    )

    @model_validator(mode="after")
    def _one_input(self) -> "DocumentIn":
        """Require exactly one of ``ocr`` and ``raw_ocr``."""
        if (self.ocr is None) == (self.raw_ocr is None):
            raise ValueError(
                f"{self.file_name}: send exactly one of 'ocr' (OCR JSON) or 'raw_ocr' (text)"
            )
        return self


class TriggerRequest(_Strict):
    """Body of ``POST /v1/cases/{case_id}/trigger``: every document's OCR in one shot."""

    documents: list[DocumentIn] = Field(min_length=1, max_length=200)
    mock_overrides: dict[str, PartyMockOverride] = Field(default_factory=dict)


class CaseInput(_Strict):
    """Everything the Anomaly Detection Agent needs for one run."""

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    lead: Lead
    documents: list[DocumentIn] = Field(min_length=1, max_length=200)
    mock_overrides: dict[str, PartyMockOverride] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_parties(self) -> "CaseInput":
        """Refuse documents or overrides for parties that are not in the lead."""
        known = set(self.lead.party_ids())
        unknown_docs = sorted({d.party_id for d in self.documents} - known)
        if unknown_docs:
            raise ValueError(
                "documents refer to parties that are not in the lead: "
                + ", ".join(unknown_docs)
            )
        unknown_mocks = sorted(set(self.mock_overrides) - known)
        if unknown_mocks:
            raise ValueError(
                "mock_overrides refer to parties that are not in the lead: "
                + ", ".join(unknown_mocks)
            )
        return self


class ExtractedFields(BaseModel):
    """Identity fields read from the OCR text of one document. Use null for anything not printed."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(
        default=None,
        description="The document holder's own full name as printed. Passport: Given "
        "Name(s) followed by Surname. Marksheet / admit letter: the student's name. "
        "Never a parent's or spouse's name.",
    )
    father_name: str | None = Field(
        default=None,
        description="Father's name as printed (Father's Name, S/O, D/O, Son of, Daughter of).",
    )
    mother_name: str | None = Field(
        default=None, description="Mother's name as printed."
    )
    spouse_name: str | None = Field(
        default=None,
        description="Spouse's name as printed (W/O, Wife of, Husband's Name, H/O).",
    )
    dob: str | None = Field(
        default=None, description="Date of birth exactly as printed."
    )
    gender: str | None = Field(default=None, description="Gender as printed.")
    address: str | None = Field(
        default=None,
        description="The holder's address as printed, lines joined with ', ', without "
        "the S/O, D/O, W/O or C/O part.",
    )
    id_number: str | None = Field(
        default=None,
        description="The document number: PAN, Aadhaar (masked as printed, e.g. XXXX "
        "XXXX 1234), passport, EPIC / voter ID, or driving licence number.",
    )
