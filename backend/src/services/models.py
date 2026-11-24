"""
File: models.py
Purpose: The lead (base truth) and the API request/response shapes.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic
"""

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from src.security.pii import aadhaar_last4

CASE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
APPLICANT = "applicant"

Relationship = Literal[
    "father",
    "mother",
    "spouse",
    "brother",
    "sister",
    "guardian",
    "uncle",
    "aunt",
    "grandfather",
    "grandmother",
    "other",
]
RELATIONSHIPS: tuple[str, ...] = Relationship.__args__  # type: ignore[attr-defined]


class _Base(BaseModel):
    """Strict model: unknown keys are refused, blank strings become None."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat a blank string as "not provided"."""
        return None if isinstance(value, str) and not value.strip() else value


class PersonLead(_Base):
    """Details of one person as captured in the lead (application form)."""

    name: str = Field(min_length=1, max_length=200)
    father_name: str | None = Field(default=None, max_length=200)
    mother_name: str | None = Field(default=None, max_length=200)
    dob: str | None = Field(default=None, max_length=60)
    gender: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=1000)
    permanent_address: str | None = Field(default=None, max_length=1000)
    mobile: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    pan: str | None = Field(default=None, max_length=20)
    aadhaar_last4: str | None = Field(default=None, max_length=12)
    passport_or_dl_number: str | None = Field(default=None, max_length=30)
    voter_id: str | None = Field(default=None, max_length=30)

    @field_validator("aadhaar_last4", mode="after")
    @classmethod
    def _only_last4(cls, value: str | None) -> str | None:
        """Keep only the last 4 Aadhaar digits, even if a full number is entered."""
        return None if value is None else aadhaar_last4(value)


class ApplicantLead(PersonLead):
    """The applicant (student), with the admission details."""

    admission_status: str | None = Field(default=None, max_length=60)
    university: str | None = Field(default=None, max_length=300)
    course: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, max_length=100)


class CoApplicantLead(PersonLead):
    """A co-applicant, with bank and employment details."""

    party_id: str = Field(pattern=r"^co_applicant_[1-9][0-9]?$")
    relationship: Relationship
    bank_name: str | None = Field(default=None, max_length=200)
    account_number: str | None = Field(default=None, max_length=40)
    employer_name: str | None = Field(default=None, max_length=300)
    employer_address: str | None = Field(default=None, max_length=1000)


class Lead(_Base):
    """The saved lead: the base truth of every comparison."""

    application_no: str | None = Field(default=None, max_length=64)
    lead_id: str | None = Field(default=None, max_length=64)
    applicant: ApplicantLead
    co_applicants: list[CoApplicantLead] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _unique_party_ids(self) -> "Lead":
        """Refuse two co-applicants with the same party_id."""
        ids = [c.party_id for c in self.co_applicants]
        if len(ids) != len(set(ids)):
            raise ValueError("co_applicants: every party_id must be unique")
        return self

    def party_ids(self) -> list[str]:
        """Return every party ID, the applicant first.

        Returns:
            ``["applicant", "co_applicant_1", ...]``.
        """
        return [APPLICANT, *(c.party_id for c in self.co_applicants)]


class LeadIn(BaseModel):
    """Body of ``POST /v1/cases/{case_id}/lead``."""

    model_config = ConfigDict(extra="forbid")
    lead: Lead


class LeadRecord(BaseModel):
    """A stored lead."""

    case_id: str
    created_at: str
    source: str
    lead: Lead


class AutofillRequest(BaseModel):
    """Body of ``POST /v1/lead/autofill``: the application form OCR and typed names."""

    model_config = ConfigDict(extra="forbid")

    ocr: dict[str, Any] | None = Field(default=None, description="OCR JSON (pages[])")
    raw_ocr: str | None = Field(
        default=None, max_length=300_000, description="or plain text"
    )
    applicant_name: str | None = Field(default=None, max_length=200)
    co_applicant_names: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _one_input(self) -> "AutofillRequest":
        """Require exactly one of ``ocr`` and ``raw_ocr``."""
        if (self.ocr is None) == (self.raw_ocr is None):
            raise ValueError("send exactly one of 'ocr' (OCR JSON) or 'raw_ocr' (text)")
        return self


class DroppedValue(BaseModel):
    """A value the LLM returned that was not kept.

    ``reason`` is ``NOT_IN_SOURCE`` (not in the OCR text) or ``MASKED`` (replaced
    by a PII tag such as ``{NAME}``).
    """

    field: str
    value: str
    reason: str


class AutofillResponse(BaseModel):
    """Lead fields read from the application form, for review in the UI."""

    lead: dict[str, Any]
    grounding: dict[str, str]
    dropped: list[DroppedValue]
    ocr: dict[str, Any]
    model_id: str
    prompt_version: str
    elapsed_ms: int


class HealthStatus(BaseModel):
    """Liveness probe answer."""

    status: Literal["ok"] = "ok"


class RunResult(BaseModel):
    """Result of one trigger: the orchestrator summary and each agent's report."""

    run_id: str
    case_id: str
    status: str
    started_at: str
    finished_at: str
    orchestrator: dict[str, Any]
    results: dict[str, Any]
