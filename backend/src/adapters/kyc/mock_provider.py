"""
File: mock_provider.py
Purpose: Mock third-party KYC provider: happy-path answers from the lead, overridable per party.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

The ``raw`` dicts imitate a vendor response. Replace this class with the real
adapter once the APIs are available; the checks do not change.
"""

import datetime as dt
from typing import Any
from typing import Literal

from src.adapters.kyc.models import BureauAddressRecord
from src.adapters.kyc.models import BureauReport
from src.adapters.kyc.models import EmailVerification
from src.adapters.kyc.models import FaceMatch
from src.adapters.kyc.models import PanAadhaarLink
from src.adapters.kyc.models import PartyContext
from src.adapters.kyc.models import VoterDlVerification


def _mask_pan(pan: str) -> str:
    """Show only the first 5 and the last character of a PAN."""
    return pan[:5] + "****" + pan[-1:] if len(pan) == 10 else "****"


class MockKycProvider:
    """Answers every call from the lead (the happy path) unless an override says otherwise."""

    name = "mock"
    is_mock = True

    def __init__(self, defaults: dict[str, Any], today: dt.date | None = None) -> None:
        self._defaults = defaults
        self._today = today or dt.date.today()

    def bureau_report(self, party: PartyContext) -> BureauReport:
        """Return the lead's name, DOB and address as the bureau record (or the override).

        Args:
            party: The party.

        Returns:
            The mocked bureau report.
        """
        forced = party.override.bureau if party.override else None
        name = forced.name if forced and forced.name is not None else party.name
        dob = forced.dob if forced and forced.dob is not None else party.dob
        if forced and forced.addresses is not None:
            addresses = [
                BureauAddressRecord(a.address, a.reported_on) for a in forced.addresses
            ]
        elif party.address:
            age = int(self._defaults.get("bureau_address_age_days", 60))
            reported = self._today - dt.timedelta(days=age)
            addresses = [BureauAddressRecord(party.address, reported)]
        else:
            addresses = []
        raw = {
            "bureau": "CIBIL (mock)",
            "consumer_name": name,
            "date_of_birth": dob,
            "addresses": [
                {"address": a.address, "date_reported": a.reported_on.isoformat()}
                for a in addresses
            ],
        }
        return BureauReport(self.name, name, dob, addresses, raw)

    def pan_aadhaar_link(
        self, party: PartyContext, pan: str, aadhaar_last4: str | None
    ) -> PanAadhaarLink:
        """Return "linked" unless the override says otherwise.

        Args:
            party: The party.
            pan: PAN number.
            aadhaar_last4: Last 4 Aadhaar digits.

        Returns:
            The mocked linkage status.
        """
        forced = party.override.pan_aadhaar_linked if party.override else None
        linked = True if forced is None else forced
        raw = {
            "api": "karza/pan-aadhaar-link (mock)",
            "pan": _mask_pan(pan),
            "aadhaar_last4": aadhaar_last4,
            "status": "LINKED" if linked else "NOT_LINKED",
        }
        return PanAadhaarLink(self.name, linked, raw)

    def verify_voter_or_dl(
        self,
        party: PartyContext,
        doc_type: Literal["VOTER_ID", "DRIVING_LICENCE"],
        id_number: str | None,
    ) -> VoterDlVerification:
        """Return "verified today" unless the override says otherwise.

        Args:
            party: The party.
            doc_type: VOTER_ID or DRIVING_LICENCE.
            id_number: Number read from the document.

        Returns:
            The mocked verification.
        """
        forced = party.override.voter_dl if party.override else None
        status = forced.status if forced else "VERIFIED"
        verified_on = None
        if status == "VERIFIED":
            verified_on = (
                forced.verified_on if forced and forced.verified_on else self._today
            )
        api = "voter-id" if doc_type == "VOTER_ID" else "driving-licence"
        raw = {
            "api": f"karza/{api} (mock)",
            "id_number_present": bool(id_number),
            "status": status,
            "verified_on": verified_on.isoformat() if verified_on else None,
        }
        return VoterDlVerification(self.name, doc_type, status, verified_on, raw)

    def verify_email(self, party: PartyContext, email: str) -> EmailVerification:
        """Return "owned" unless the override says otherwise.

        Args:
            party: The party.
            email: Email from the lead.

        Returns:
            The mocked ownership check.
        """
        forced = party.override.email_ownership_verified if party.override else None
        owned = True if forced is None else forced
        raw = {"api": "email-ownership (mock)", "ownership_verified": owned}
        return EmailVerification(self.name, owned, raw)

    def face_match(self, party: PartyContext) -> FaceMatch:
        """Return the default match (or the override).

        Args:
            party: The party.

        Returns:
            The mocked face match.
        """
        forced = party.override.face_match if party.override else None
        pct = (
            forced.match_pct
            if forced
            else float(self._defaults.get("face_match_pct", 92.0))
        )
        status = (
            forced.status
            if forced
            else self._defaults.get("face_match_status", "SUCCESS")
        )
        raw = {"api": "face-match (mock)", "match_pct": pct, "status": status}
        return FaceMatch(self.name, pct, status, raw)
