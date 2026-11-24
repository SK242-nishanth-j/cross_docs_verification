"""
File: base.py
Purpose: Third-party KYC provider interface. Implement it once per vendor (e.g. Karza) to replace the mock.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

import dataclasses
import datetime as dt
from typing import Any
from typing import Literal
from typing import Protocol

from src.adapters.kyc.models import BureauReport
from src.adapters.kyc.models import EmailVerification
from src.adapters.kyc.models import FaceMatch
from src.adapters.kyc.models import PanAadhaarLink
from src.adapters.kyc.models import PartyContext
from src.adapters.kyc.models import VoterDlVerification


class KycProvider(Protocol):
    """Bureau, Karza, email and face match calls used by the KYC checks."""

    name: str
    is_mock: bool

    def bureau_report(self, party: PartyContext) -> BureauReport:
        """Return the bureau identity section of one party.

        Args:
            party: The party.

        Returns:
            Name, DOB and reported addresses.
        """
        ...

    def pan_aadhaar_link(
        self, party: PartyContext, pan: str, aadhaar_last4: str | None
    ) -> PanAadhaarLink:
        """Return whether PAN and Aadhaar are linked.

        Args:
            party: The party.
            pan: PAN number.
            aadhaar_last4: Last 4 Aadhaar digits.

        Returns:
            The linkage status.
        """
        ...

    def verify_voter_or_dl(
        self,
        party: PartyContext,
        doc_type: Literal["VOTER_ID", "DRIVING_LICENCE"],
        id_number: str | None,
    ) -> VoterDlVerification:
        """Return the Voter ID / driving licence verification status.

        Args:
            party: The party.
            doc_type: VOTER_ID or DRIVING_LICENCE.
            id_number: Number read from the document.

        Returns:
            The verification status and date.
        """
        ...

    def verify_email(self, party: PartyContext, email: str) -> EmailVerification:
        """Return whether the email ownership is verified.

        Args:
            party: The party.
            email: Email from the lead.

        Returns:
            The ownership status.
        """
        ...

    def face_match(self, party: PartyContext) -> FaceMatch:
        """Return the face match percentage and status.

        Args:
            party: The party.

        Returns:
            Match percentage and status.
        """
        ...


def to_jsonable(value: Any) -> Any:
    """Turn dataclasses and dates into plain JSON values.

    Args:
        value: A dataclass instance, mapping, list or scalar.

    Returns:
        The same data with dates as ISO text.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value
