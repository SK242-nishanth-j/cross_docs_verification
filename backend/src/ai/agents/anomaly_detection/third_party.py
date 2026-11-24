"""
File: third_party.py
Purpose: Third-party checks (mocked APIs): bureau address, PAN-Aadhaar link, Voter ID / DL, email, face match.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only

The bureau name and DOB are sources of the NAME / DOB cross-checks. The bureau
address is compared here: by cross_verify, or by the LLM in the full-LLM modes.
"""

import datetime as dt
import re
from collections.abc import Callable
from typing import Any
from typing import Literal

from src.adapters.kyc.base import KycProvider
from src.adapters.kyc.base import to_jsonable
from src.adapters.kyc.models import BureauAddressRecord
from src.adapters.kyc.models import BureauReport
from src.ai.agents.anomaly_detection.comparison import COLOR_RANK
from src.ai.agents.anomaly_detection.comparison import Finding
from src.ai.agents.anomaly_detection.comparison import finding
from src.ai.agents.anomaly_detection.schemas import CaseInput
from src.ai.agents.anomaly_detection.sources import Party
from src.ai.agents.anomaly_detection.sources import party_context

# (lead address, bureau addresses) -> one comparison per bureau address
AddressCompare = Callable[[str, list[str], str], list[dict[str, Any]]]

_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)
_STATUS = {
    "green": "match",
    "yellow": "warning",
    "red": "mismatch",
    "grey": "not_evaluated",
}
_DAYS_PER_MONTH = 30.44


def _common(party: Party, check: str, config: dict[str, Any]) -> dict[str, Any]:
    """Fields every finding of one third-party check shares."""
    meta = config["third_party"]["checks"][check]
    return {
        "check_id": f"{party.party_id}.{check}",
        "party_id": party.party_id,
        "category": "third_party",
        "check": check,
        "title": f"{meta['title']} (mock)",
        "severity": meta["severity"],
        "mitigant": meta["mitigant"],
    }


def recent_addresses(
    report: BureauReport, months: int, today: dt.date
) -> list[BureauAddressRecord]:
    """Return the bureau addresses reported within the window.

    Args:
        report: The person's bureau report.
        months: Window in months.
        today: Reference date.

    Returns:
        The recent addresses, newest order kept as reported.
    """
    cutoff = today - dt.timedelta(days=round(months * _DAYS_PER_MONTH))
    return [a for a in report.addresses if a.reported_on >= cutoff]


def bureau_address(
    party: Party,
    report: BureauReport,
    compare: AddressCompare,
    config: dict[str, Any],
    today: dt.date,
) -> Finding:
    """The lead address must match a bureau address reported in the window.

    Args:
        party: The person.
        report: The person's bureau report.
        compare: Compares the lead address with each bureau address.
        config: The anomaly configuration.
        today: Reference date.

    Returns:
        The finding (best match among the recent bureau addresses).
    """
    common = _common(party, "BUREAU_ADDRESS", config)
    months = int(config["third_party"]["bureau_address_window_months"])
    recent = recent_addresses(report, months, today)
    evidence = {
        "provider": report.provider,
        "window_months": months,
        "response": to_jsonable(report.raw),
    }
    address = party.lead.address
    base = {"value": address, "source": party.lead_path("address")}
    if not address or not recent:
        why = (
            "The lead has no address for this person."
            if not address
            else f"The bureau reported no address in the last {months} months."
        )
        return finding(
            **common, status="not_evaluated", base=base, evidence=evidence, message=why
        )
    comps = compare(address, [a.address for a in recent], party.party_id)
    comparisons = [
        {
            "source_kind": "bureau",
            "provider": report.provider,
            "value": a.address,
            "reported_on": a.reported_on.isoformat(),
            **c,
        }
        for a, c in zip(recent, comps, strict=True)
    ]
    best = min(comparisons, key=lambda c: COLOR_RANK[c["color"]])
    status = _STATUS[best["color"]]
    message = (
        f"The lead address matches a bureau address reported on {best['reported_on']}."
        if status == "match"
        else f"The lead address does not fully match any bureau address from the last {months} months."
    )
    return finding(
        **common,
        status=status,
        base=base,
        comparisons=comparisons,
        evidence=evidence,
        message=message,
    )


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
        if e.doc_type == "AADHAAR":
            digits = re.sub(r"\D", "", e.get("id_number") or "")
            if len(digits) >= 4:
                return digits[-4:]
    return party.lead.aadhaar_last4


def pan_aadhaar_link(
    party: Party, provider: KycProvider, case: CaseInput, config: dict[str, Any]
) -> Finding:
    """PAN and Aadhaar must be linked; otherwise a sanction condition is added.

    Args:
        party: The person.
        provider: Third-party provider (mock).
        case: The case input.
        config: The anomaly configuration.

    Returns:
        The finding.
    """
    common = _common(party, "PAN_AADHAAR_LINK", config)
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
        sanction_condition=str(config["third_party"]["pan_link_condition"]),
        evidence=evidence,
        message="PAN and Aadhaar are NOT linked. Sanction condition added.",
    )


def voter_dl(
    party: Party,
    provider: KycProvider,
    case: CaseInput,
    config: dict[str, Any],
    today: dt.date,
) -> list[Finding]:
    """Every Voter ID / driving licence must be verified through the API.

    Args:
        party: The person.
        provider: Third-party provider (mock).
        case: The case input.
        config: The anomaly configuration.
        today: Reference date (for the optional verification window).

    Returns:
        One finding per Voter ID / driving licence document.
    """
    window = config["third_party"].get("voter_dl_verification_window_days")
    out = []
    for e in party.extractions:
        if e.doc_type not in ("VOTER_ID", "DRIVING_LICENCE"):
            continue
        common = {
            **_common(party, "VOTER_DL_VERIFICATION", config),
            "check_id": f"{party.party_id}.VOTER_DL_VERIFICATION.{e.document_index}",
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
        late = bool(
            window and res.verified_on and (today - res.verified_on).days > int(window)
        )
        if res.status != "VERIFIED" or late:
            message = (
                f"{label} ({e.file_name}) is not verified. Manual check and CM justification required."
                if res.status != "VERIFIED"
                else f"{label} was verified outside the accepted {window}-day window."
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
                    message=f"{label} ({e.file_name}) is verified.",
                )
            )
    return out


def email_check(
    party: Party, provider: KycProvider, case: CaseInput, config: dict[str, Any]
) -> Finding | None:
    """The lead email must be well formed and owned by the person.

    Args:
        party: The person.
        provider: Third-party provider (mock).
        case: The case input.
        config: The anomaly configuration.

    Returns:
        The finding, or None when the lead has no email for this person.
    """
    email = (party.lead.email or "").strip()
    if not email:
        return None
    common = _common(party, "EMAIL_VALIDATION", config)
    base = {"value": email, "source": party.lead_path("email")}
    if not _EMAIL.fullmatch(email):
        return finding(
            **common, status="mismatch", base=base, message="The email ID is not valid."
        )
    res = provider.verify_email(party_context(party, case), email)
    evidence = {"provider": res.provider, "response": to_jsonable(res.raw)}
    owned = res.ownership_verified
    return finding(
        **common,
        status="match" if owned else "warning",
        base=base,
        evidence=evidence,
        message="The email format is valid and ownership is verified."
        if owned
        else "The email format is valid, but ownership is not verified.",
    )


def face_match(
    party: Party, provider: KycProvider, case: CaseInput, config: dict[str, Any]
) -> Finding:
    """Face match must be at least the threshold with status SUCCESS.

    Args:
        party: The person.
        provider: Third-party provider (mock).
        case: The case input.
        config: The anomaly configuration.

    Returns:
        The finding; a failure is critical and needs a CM justification.
    """
    common = _common(party, "FACE_MATCH", config)
    minimum = float(config["third_party"]["face_match_min_pct"])
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


def evaluate_third_party(
    parties: list[Party],
    bureau: dict[str, BureauReport],
    provider: KycProvider,
    compare: AddressCompare,
    case: CaseInput,
    config: dict[str, Any],
    today: dt.date,
) -> list[Finding]:
    """Run every third-party check for every person, in check order.

    Args:
        parties: People in check order.
        bureau: Bureau report of each person.
        provider: Third-party provider (mock).
        compare: Compares the lead address with the bureau addresses.
        case: The case input.
        config: The anomaly configuration.
        today: Reference date.

    Returns:
        The third-party findings.
    """
    out: list[Finding] = []
    for p in parties:
        out.append(bureau_address(p, bureau[p.party_id], compare, config, today))
        out.append(pan_aadhaar_link(p, provider, case, config))
        out.extend(voter_dl(p, provider, case, config, today))
        email = email_check(p, provider, case, config)
        if email:
            out.append(email)
        out.append(face_match(p, provider, case, config))
    return out
