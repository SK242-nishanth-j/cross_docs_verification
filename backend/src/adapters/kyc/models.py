"""
File: models.py
Purpose: Third-party KYC answers (bureau, Karza, email, face match) and the mock overrides.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic
"""

import datetime as dt
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BureauAddress(_Strict):
    """One address reported by the bureau."""

    address: str = Field(min_length=1, max_length=1000)
    reported_on: dt.date


class BureauOverride(_Strict):
    """Forced bureau answer for one party."""

    name: str | None = Field(default=None, max_length=200)
    dob: str | None = Field(default=None, max_length=60)
    addresses: list[BureauAddress] | None = Field(default=None, max_length=20)


class VoterDlOverride(_Strict):
    """Forced Karza Voter ID / DL answer."""

    status: Literal["VERIFIED", "NOT_VERIFIED"] = "VERIFIED"
    verified_on: dt.date | None = None


class FaceMatchOverride(_Strict):
    """Forced face match answer."""

    match_pct: float = Field(ge=0, le=100)
    status: Literal["SUCCESS", "FAILED", "PENDING"] = "SUCCESS"


class PartyMockOverride(_Strict):
    """Forces mocked third-party answers for one party (until the real APIs are connected)."""

    bureau: BureauOverride | None = None
    pan_aadhaar_linked: bool | None = None
    voter_dl: VoterDlOverride | None = None
    email_ownership_verified: bool | None = None
    face_match: FaceMatchOverride | None = None


@dataclass(frozen=True)
class PartyContext:
    """What a provider is told about one party."""

    party_id: str
    name: str
    dob: str | None
    address: str | None
    email: str | None
    pan: str | None
    override: PartyMockOverride | None = None


@dataclass(frozen=True)
class BureauAddressRecord:
    """An address with the date the bureau reported it."""

    address: str
    reported_on: dt.date


@dataclass(frozen=True)
class BureauReport:
    """CIBIL / CRIF identity section (name, DOB and addresses)."""

    provider: str
    name: str | None
    dob: str | None
    addresses: list[BureauAddressRecord]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PanAadhaarLink:
    """Karza PAN-Aadhaar linkage."""

    provider: str
    linked: bool
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VoterDlVerification:
    """Karza Voter ID / Driving Licence verification."""

    provider: str
    doc_type: Literal["VOTER_ID", "DRIVING_LICENCE"]
    status: Literal["VERIFIED", "NOT_VERIFIED"]
    verified_on: dt.date | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmailVerification:
    """Email ownership."""

    provider: str
    ownership_verified: bool
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FaceMatch:
    """Face match system result."""

    provider: str
    match_pct: float
    status: Literal["SUCCESS", "FAILED", "PENDING"]
    raw: dict[str, Any] = field(default_factory=dict)
