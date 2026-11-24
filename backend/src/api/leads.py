"""
File: leads.py
Purpose: Lead endpoints: application-form auto-fill (file upload) and the reviewed lead (base truth).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

import json
import re
from typing import Annotated
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import Path
from fastapi import UploadFile
from fastapi import status

from src.api.dependencies import get_autofill_service
from src.api.dependencies import get_case_service
from src.config.settings import Settings
from src.config.settings import get_anomaly_config
from src.config.settings import get_settings
from src.security.uploads import read_upload
from src.services.autofill_service import AutofillService
from src.services.case_service import CaseService
from src.services.errors import InvalidInputError
from src.services.models import CASE_ID_PATTERN
from src.services.models import AutofillResponse
from src.services.models import LeadIn
from src.services.models import LeadRecord

router = APIRouter(prefix="/v1", tags=["leads"])
CaseId = Annotated[
    str, Path(pattern=CASE_ID_PATTERN, description="Case / application number")
]
CASE_ID_PATTERN_RE = re.compile(CASE_ID_PATTERN)
_MAX_NAMES = 6
_MAX_NAME_LENGTH = 200


def _hints(applicant_name: str, co_applicant_names: str) -> list[str]:
    """Turn the names typed in the UI into hints for the LLM."""
    try:
        names: Any = json.loads(co_applicant_names or "[]")
    except json.JSONDecodeError as exc:
        raise InvalidInputError("co_applicant_names must be a JSON list") from exc
    if not isinstance(names, list) or len(names) > _MAX_NAMES:
        raise InvalidInputError(f"co_applicant_names: a list of at most {_MAX_NAMES}")
    hints = (
        [f"Applicant (typed by the user): {applicant_name.strip()}"]
        if applicant_name.strip()
        else []
    )
    hints += [
        f"Co-applicant {n} (typed by the user): {str(name).strip()[:_MAX_NAME_LENGTH]}"
        for n, name in enumerate(names, start=1)
        if str(name).strip()
    ]
    return hints


@router.post(
    "/lead/autofill",
    response_model=AutofillResponse,
    summary="Read the lead from an application form (file upload)",
)
def autofill(
    file: Annotated[UploadFile, File(description="The application form")],
    service: Annotated[AutofillService, Depends(get_autofill_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    case_id: Annotated[str, Form(max_length=64)] = "",
    applicant_name: Annotated[str, Form(max_length=_MAX_NAME_LENGTH)] = "",
    co_applicant_names: Annotated[str, Form(max_length=2000)] = "[]",
) -> AutofillResponse:
    """Read every lead field from the application form; the file and its JSON are stored.

    Args:
        file: The application form (format depends on the mode).
        service: The auto-fill service.
        settings: Application settings (upload size limit).
        case_id: The case; empty takes the form's application number.
        applicant_name: Applicant name typed in the UI (hint).
        co_applicant_names: JSON list of co-applicant names typed in the UI (hints).

    Returns:
        The lead fields for review.

    Raises:
        InvalidInputError: If the file or the case ID is not accepted.
    """
    config = get_anomaly_config()
    accepts = list(config["modes"][config["mode"]]["accepts"])
    content = read_upload(file, accepts, settings.max_request_bytes)
    case = case_id.strip() or None
    if case is not None and not CASE_ID_PATTERN_RE.fullmatch(case):
        raise InvalidInputError("case_id: letters, digits, '-' and '_' only")
    return service.autofill(
        file_name=file.filename or "application_form",
        content=content,
        case_id=case,
        hints=_hints(applicant_name, co_applicant_names),
    )


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
