"""
File: leads.py
Purpose: Application-form auto-fill and lead creation (the base truth of a case).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Path
from fastapi import status

from src.api.dependencies import get_autofill_service
from src.api.dependencies import get_case_service
from src.services.autofill_service import AutofillService
from src.services.case_service import CaseService
from src.services.models import CASE_ID_PATTERN
from src.services.models import AutofillRequest
from src.services.models import AutofillResponse
from src.services.models import LeadIn
from src.services.models import LeadRecord

router = APIRouter(prefix="/v1", tags=["leads"])
CaseId = Annotated[
    str, Path(pattern=CASE_ID_PATTERN, description="Case / application number")
]


@router.post(
    "/lead/autofill",
    response_model=AutofillResponse,
    summary="Read the lead from an application form",
)
def autofill(
    body: AutofillRequest,
    service: Annotated[AutofillService, Depends(get_autofill_service)],
) -> AutofillResponse:
    """Read every lead field from the application form OCR. Nothing is stored.

    Args:
        body: The application form OCR and the names typed in the UI.
        service: The auto-fill service.

    Returns:
        The grounded lead fields for review.
    """
    return service.autofill(body)


@router.post(
    "/cases/{case_id}/lead",
    response_model=LeadRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Save the reviewed lead (base truth)",
)
def create_lead(
    case_id: CaseId,
    body: LeadIn,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> LeadRecord:
    """Save the lead of a case.

    Args:
        case_id: The case.
        body: The reviewed lead.
        service: The case service.

    Returns:
        The stored lead record.
    """
    return service.create_lead(case_id, body.lead)


@router.get(
    "/cases/{case_id}/lead", response_model=LeadRecord, summary="Read the saved lead"
)
def get_lead(
    case_id: CaseId, service: Annotated[CaseService, Depends(get_case_service)]
) -> LeadRecord:
    """Return the saved lead of a case.

    Args:
        case_id: The case.
        service: The case service.

    Returns:
        The lead record.
    """
    return service.get_lead(case_id)
