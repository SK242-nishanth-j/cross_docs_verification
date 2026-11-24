"""
File: cases.py
Purpose: Trigger the Orchestrator Agent for a case and read the latest result.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Path

from src.ai.agents.anomaly_detection.schemas import TriggerRequest
from src.api.dependencies import get_case_service
from src.services.case_service import CaseService
from src.services.models import CASE_ID_PATTERN
from src.services.models import RunResult

router = APIRouter(prefix="/v1/cases", tags=["cases"])
CaseId = Annotated[
    str, Path(pattern=CASE_ID_PATTERN, description="Case / application number")
]


@router.post(
    "/{case_id}/trigger", response_model=RunResult, summary="Run the agents on a case"
)
def trigger(
    case_id: CaseId,
    body: TriggerRequest,
    service: Annotated[CaseService, Depends(get_case_service)],
) -> RunResult:
    """Run the Orchestrator Agent (and through it the Anomaly Detection Agent).

    Args:
        case_id: The case; its lead must exist.
        body: Every document's OCR in one shot, plus the mock overrides.
        service: The case service.

    Returns:
        The run result with the orchestrator summary and the full report.
    """
    return service.trigger(case_id, body)


@router.get(
    "/{case_id}/result", response_model=RunResult, summary="Read the latest result"
)
def get_result(
    case_id: CaseId, service: Annotated[CaseService, Depends(get_case_service)]
) -> RunResult:
    """Return the latest result of a case.

    Args:
        case_id: The case.
        service: The case service.

    Returns:
        The run result.
    """
    return service.get_result(case_id)
