"""
File: kyc_rules.py
Purpose: Third-party KYC checks KY-02..KY-06, run after the cross-verification (APIs mocked for now).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

  KY-01  Name / DOB vs CIBIL/CRIF    bureau name and DOB are sources in the NAME / DOB pairs
  KY-02  Lead address vs bureau       addresses of the last 12 months; passes if one matches
  KY-03  PAN-Aadhaar linkage (Karza)  not linked -> sanction condition
  KY-04  Voter ID / DL (Karza)        not verified -> manual check, CM justification
  KY-05  Email ID                     format (code) + ownership (mock)
  KY-06  Face match >= 75% + SUCCESS  otherwise CRITICAL, CM justification in CAM OTHER REMARKS
"""

import datetime as dt
import re
from typing import Any
from typing import Literal

from src.adapters.kyc.base import KycProvider
from src.adapters.kyc.base import to_jsonable
from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection.bureau_rules import ky02
from src.ai.agents.anomaly_detection.findings import Finding
from src.ai.agents.anomaly_detection.findings import finding
from src.ai.agents.anomaly_detection.findings import rule_fields
from src.ai.agents.anomaly_detection.pairs import Verify
from src.ai.agents.anomaly_detection.parties import Party
from src.ai.agents.anomaly_detection.parties import party_context
from src.ai.agents.anomaly_detection.schemas import CaseInput

PAN_LINK_CONDITION = "Aadhaar to be linked to PAN before disbursement"
_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)
_STATUS = {"green": "match", "yellow": "warning", "red": "mismatch"}


def _pan_number(party: Party) -> str | None:
    """PAN from the PAN card, else from the lead."""
    for e in party.readable():
        number = e.get("id_number")
        if e.doc_type == "PAN" and number:
            return re.sub(r"\s+", "", number).upper()
    return re.sub(r"\s+", "", party.lead.pan).upper() if party.lead.pan else None


def _aadhaar_last4(party: Party) -> str | None:
    """Last 4 Aadhaar digits from the Aadhaar card, else from the lead."""
    for e in party.readable():
        digits = (
            re.sub(r"\D", "", e.get("id_number") or "")
            if e.doc_type == "AADHAAR"
            else ""
        )
        if len(digits) >= 4:
            return digits[-4:]
    return party.lead.aadhaar_last4


def ky03(
    party: Party, provider: KycProvider, case: CaseInput, rules: dict[str, Any]
) -> Finding:
    """KY-03: PAN and Aadhaar must be linked; otherwise add a sanction condition.

    Args:
        party: The party.
        provider: Third-party provider.
        case: The case input.
        rules: The anomaly rules configuration.

    Returns:
        The finding.
    """
    common = rule_fields(party.party_id, "KY-03", rules, "PAN_AADHAAR_LINK")
    pan, last4 = _pan_number(party), _aadhaar_last4(party)
    if not pan or not last4:
        missing = " and ".join(
            x for x, ok in (("PAN number", pan), ("Aadhaar number", last4)) if not ok
        )
        return finding(
            **common,
            status="not_evaluated",
            message=f"{missing} not available, so the API was not called.",
        )
    res = provider.pan_aadhaar_link(party_context(party, case), pan, last4)
    evidence = {"provider": res.provider, "response": to_jsonable(res.raw)}
    if res.linked:
        return finding(
            **common,
            status="match",
            message="PAN and Aadhaar are linked.",
            evidence=evidence,
        )
    return finding(
        **common,
        status="warning",
        sanction_condition=PAN_LINK_CONDITION,
        evidence=evidence,
        message="PAN and Aadhaar are NOT linked. Sanction condition added.",
    )


def ky04(
    party: Party,
    provider: KycProvider,
    case: CaseInput,
    rules: dict[str, Any],
    today: dt.date,
) -> list[Finding]:
    """KY-04: every Voter ID / driving licence must be verified through Karza.

    Args:
        party: The party.
        provider: Third-party provider.
        case: The case input.
        rules: The anomaly rules configuration.
        today: Reference date (for the optional verification window).

    Returns:
        One finding per Voter ID / driving licence document.
    """
    window = rules["kyc_rules"].get("voter_dl_verification_window_days")
    out = []
    for e in party.extractions:
        if e.doc_type not in ("VOTER_ID", "DRIVING_LICENCE"):
            continue
        common = {
            **rule_fields(party.party_id, "KY-04", rules, "VOTER_DL_VERIFICATION"),
            "check_id": f"{party.party_id}.KY-04.{e.document_index}",
        }
        doc_type: Literal["VOTER_ID", "DRIVING_LICENCE"] = (
            "VOTER_ID" if e.doc_type == "VOTER_ID" else "DRIVING_LICENCE"
        )
        res = provider.verify_voter_or_dl(
            party_context(party, case), doc_type, e.get("id_number")
        )
        evidence = {
            "provider": res.provider,
            "file_name": e.file_name,
            "response": to_jsonable(res.raw),
            "window_days": window,
        }
        label = "Voter ID" if doc_type == "VOTER_ID" else "Driving licence"
        if res.status != "VERIFIED":
            message = (
                f"{label} ({e.file_name}) is not verified through Karza. "
                "Manual check and CM justification required."
            )
            out.append(
                finding(
                    **common,
                    status="warning",
                    cm_justification_required=True,
                    evidence=evidence,
                    message=message,
                )
            )
        elif (
            window and res.verified_on and (today - res.verified_on).days > int(window)
        ):
            message = (
                f"{label} was verified on {res.verified_on.isoformat()}, outside the "
                f"accepted {window}-day window."
            )
            out.append(
                finding(
                    **common,
                    status="warning",
                    cm_justification_required=True,
                    evidence=evidence,
                    message=message,
                )
            )
        else:
            out.append(
                finding(
                    **common,
                    status="match",
                    evidence=evidence,
                    message=f"{label} ({e.file_name}) is verified through Karza.",
                )
            )
    return out


def ky05(
    party: Party, provider: KycProvider, case: CaseInput, rules: dict[str, Any]
) -> Finding | None:
    """KY-05: the lead email must be well formed and owned by the party.

    Args:
        party: The party.
        provider: Third-party provider.
        case: The case input.
        rules: The anomaly rules configuration.

    Returns:
        The finding, or None when the lead has no email for this party.
    """
    email = (party.lead.email or "").strip()
    if not email:
        return None
    common = rule_fields(party.party_id, "KY-05", rules, "EMAIL_VALIDATION")
    base = {"value": email, "source": party.lead_path("email")}
    if not _EMAIL.fullmatch(email):
        return finding(
            **common,
            status="mismatch",
            base=base,
            message=f"The email ID '{email}' is not valid.",
        )
    res = provider.verify_email(party_context(party, case), email)
    evidence = {"provider": res.provider, "response": to_jsonable(res.raw)}
    if not res.ownership_verified:
        return finding(
            **common,
            status="warning",
            base=base,
            evidence=evidence,
            message="The email format is valid, but ownership is not verified.",
        )
    return finding(
        **common,
        status="match",
        base=base,
        evidence=evidence,
        message="The email format is valid and ownership is verified.",
    )


def ky06(
    party: Party, provider: KycProvider, case: CaseInput, rules: dict[str, Any]
) -> Finding:
    """KY-06: face match must be at least the threshold (75%) with status SUCCESS.

    Args:
        party: The party.
        provider: Third-party provider.
        case: The case input.
        rules: The anomaly rules configuration.

    Returns:
        The finding; a failure is critical and needs a CM justification.
    """
    common = rule_fields(party.party_id, "KY-06", rules, "FACE_MATCH")
    minimum = float(rules["kyc_rules"]["face_match_min_pct"])
    res = provider.face_match(party_context(party, case))
    evidence = {
        "provider": res.provider,
        "min_pct": minimum,
        "response": to_jsonable(res.raw),
    }
    if res.status == "SUCCESS" and res.match_pct >= minimum:
        message = f"Face match {res.match_pct:g}% (status {res.status}), at or above {minimum:g}%."
        return finding(**common, status="match", evidence=evidence, message=message)
    problems = []
    if res.match_pct < minimum:
        problems.append(f"{res.match_pct:g}% is below {minimum:g}%")
    if res.status != "SUCCESS":
        problems.append(f"status is {res.status}")
    message = (
        "CRITICAL: face match "
        + " and ".join(problems)
        + ". The CM must justify this in OTHER REMARKS in the CAM before sanction."
    )
    return finding(
        **common,
        status="mismatch",
        critical=True,
        cm_justification_required=True,
        evidence=evidence,
        message=message,
    )


def evaluate_kyc_rules(
    parties: list[Party],
    bureau: dict[str, BureauReport],
    provider: KycProvider,
    verify: Verify,
    case: CaseInput,
    rules: dict[str, Any],
    today: dt.date,
) -> list[Finding]:
    """Run KY-02..KY-06 for every party, in check order.

    Args:
        parties: Parties in check order.
        bureau: Bureau report of each party.
        provider: Third-party provider.
        verify: The cross_verify verify function (for KY-02).
        case: The case input.
        rules: The anomaly rules configuration.
        today: Reference date.

    Returns:
        The third-party findings.
    """
    out: list[Finding] = []
    for p in parties:
        out.append(ky02(p, bureau[p.party_id], verify, rules, today))
        out.append(ky03(p, provider, case, rules))
        out.extend(ky04(p, provider, case, rules, today))
        email = ky05(p, provider, case, rules)
        if email:
            out.append(email)
        out.append(ky06(p, provider, case, rules))
    return out
