"""
File: schemas.py
Purpose: Agent inputs, the per-document extraction record and the full-LLM answer schema.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic
"""

import json
from dataclasses import dataclass
from dataclasses import field
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


class DocumentMeta(BaseModel):
    """Who an uploaded file belongs to and what it is (chosen in the UI)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    file_name: str = Field(min_length=1, max_length=255)
    party_id: str = Field(pattern=PARTY_ID_PATTERN)
    doc_type: DocType


class DocumentIn(DocumentMeta):
    """One uploaded document with its bytes (image, PDF, OCR JSON or structured JSON)."""

    content: bytes = Field(repr=False, exclude=True)
    stored_as: str | None = None

    def json_content(self) -> Any:
        """Parse the file as JSON.

        Returns:
            The parsed JSON.

        Raises:
            ValueError: If the file is not valid UTF-8 JSON.
        """
        try:
            return json.loads(self.content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{self.file_name}: not a valid JSON file") from exc

    def ocr_input(self) -> tuple[dict[str, Any] | None, str | None]:
        """Read the file as an OCR JSON (``{pages: [...]}``) or as plain OCR text.

        Returns:
            ``(ocr_json, None)`` for a JSON file, ``(None, text)`` for a text file.

        Raises:
            ValueError: If a JSON file has no ``pages`` list, or the text is not UTF-8.
        """
        if self.file_name.lower().endswith(".json"):
            data = self.json_content()
            if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
                raise ValueError(f"{self.file_name}: not an OCR JSON (no 'pages' list)")
            return data, None
        try:
            return None, self.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{self.file_name}: not a UTF-8 text file") from exc


class CaseInput(BaseModel):
    """Everything the Anomaly Detection Agent needs for one run."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=CASE_ID_PATTERN)
    lead: Lead
    documents: list[DocumentIn] = Field(min_length=1, max_length=200)
    mock_overrides: dict[str, PartyMockOverride] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_parties(self) -> "CaseInput":
        """Refuse documents or overrides for parties that are not in the lead."""
        known = set(self.lead.party_ids())
        unknown = sorted(
            ({d.party_id for d in self.documents} | set(self.mock_overrides)) - known
        )
        if unknown:
            raise ValueError(
                "documents or mock overrides refer to parties that are not in the "
                "lead: " + ", ".join(unknown)
            )
        return self


class ExtractedFields(BaseModel):
    """Identity fields read from one document. null for anything not printed."""

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
        description="The document number: PAN, Aadhaar (only the last 4 digits, as "
        "XXXX XXXX 1234), passport, EPIC / voter ID, or driving licence number.",
    )


FIELDS: tuple[str, ...] = tuple(ExtractedFields.model_fields)


# ---- Answer of the full-LLM modes (one call per person) ----
ID_TYPES = {"pan", "aadhaar", "passport", "driving_licence", "voter_id"}
CODES_BY_TYPE = {
    "name": [
        "EXACT", "NORMALIZED_EQUAL", "HONORIFIC_IGNORED", "CARE_OF_REMOVED",
        "LABEL_STRIPPED", "NON_LATIN_TEXT_IGNORED", "TOKEN_ORDER_DIFFERENT",
        "SPACING_DIFFERENCE", "INITIAL_EXPANDED", "MISSING_TOKEN", "EXTRA_TOKEN",
        "MISSING_INITIALS", "EXTRA_INITIALS", "TOKEN_CONFLICT", "INSUFFICIENT_NAME",
        "UNPARSEABLE",
    ],
    "dob": [
        "EXACT", "NORMALIZED_EQUAL", "LABEL_STRIPPED", "DATE_DIFFERENT",
        "DATE_IMPLAUSIBLE", "UNPARSEABLE",
    ],
    "address": [
        "EXACT", "NORMALIZED_EQUAL", "CARE_OF_REMOVED", "LABEL_STRIPPED",
        "SPELLING_VARIANT", "INCOMPLETE_ADDRESS", "NUMBER_SUBSET", "PINCODE_NEAR",
        "WORDS_PARTIAL", "NO_ANCHOR_MATCH", "PINCODE_MISMATCH", "CITY_MISMATCH",
        "NUMBER_MISMATCH", "WORDS_MISMATCH",
    ],
    "id": [
        "EXACT", "NORMALIZED_EQUAL", "ID_MASKED", "ID_OCR_VARIANT", "ID_PARTIAL",
        "ID_FORMAT_DOUBTFUL", "ID_DIFFERENT", "UNPARSEABLE",
    ],
}  # fmt: skip


class LlmReason(BaseModel):
    """One reason code with a short explanation."""

    code: str = Field(description="A code from the closed list of the field type.")
    message: str = Field(description="Short explanation, at most 160 characters.")


class LlmComparison(BaseModel):
    """One source of a check compared with the check's base."""

    source: str = Field(
        description="Key of the compared source: k1, k2 ... or d1, d2 ..."
    )
    color: Literal["green", "yellow", "red"]
    reasons: list[LlmReason] = Field(default_factory=list)


class LlmCheck(BaseModel):
    """The comparisons of one check."""

    check_id: str
    comparisons: list[LlmComparison] = Field(default_factory=list)


class LlmDocument(BaseModel):
    """The fields read from one document."""

    document: str = Field(description="Document key: d1, d2 ...")
    fields: ExtractedFields


class PersonAnswer(BaseModel):
    """Every document of one person read, and every check compared."""

    documents: list[LlmDocument] = Field(default_factory=list)
    checks: list[LlmCheck] = Field(default_factory=list)


def check_type(field_type: str) -> str:
    """Return the rule family of a group's field type (all ID numbers are "id").

    Args:
        field_type: The group's cross_verify type, for example ``pan``.

    Returns:
        ``name``, ``dob``, ``address`` or ``id``.
    """
    return "id" if field_type in ID_TYPES else field_type


def reason_codes(reasons: dict[str, str], overrides: dict[str, str]) -> dict[str, Any]:
    """Return the closed list of codes per field type, with their severity.

    Args:
        reasons: cross_verify ``REASONS`` (code -> severity).
        overrides: ``severity_overrides`` of the cross_verify configuration.

    Returns:
        ``{type: [{"code", "severity"}]}`` for the prompt.
    """
    return {
        t: [{"code": c, "severity": overrides.get(c, reasons[c])} for c in codes]
        for t, codes in CODES_BY_TYPE.items()
    }


@dataclass
class DocumentExtraction:
    """What was read from one document (by the LLM or from its structured JSON)."""

    document_index: int
    party_id: str
    doc_type: str
    file_name: str
    read_by: str  # llm | structured
    status: str = "ok"  # ok | failed
    fields: dict[str, str] = field(default_factory=dict)
    grounding: dict[str, str] = field(default_factory=dict)
    dropped: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    stored_as: str | None = None
    elapsed_ms: int = 0

    def get(self, name: str) -> str | None:
        """Return one extracted field.

        Args:
            name: Field name, for example ``dob``.

        Returns:
            The value, or None when it was not read.
        """
        return self.fields.get(name)

    def as_report(self) -> dict[str, Any]:
        """Return the extraction for the report and for its stored JSON file.

        Returns:
            File, party, type, fields, how they were found and dropped values.
        """
        return {
            "document_index": self.document_index,
            "file_name": self.file_name,
            "party_id": self.party_id,
            "doc_type": self.doc_type,
            "read_by": self.read_by,
            "status": self.status,
            "fields": self.fields,
            "grounding": self.grounding,
            "dropped": self.dropped,
            "error": self.error,
            "stats": self.stats,
            "stored_as": self.stored_as,
            "elapsed_ms": self.elapsed_ms,
        }
