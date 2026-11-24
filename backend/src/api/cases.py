"""
File: cases.py
Purpose: Case endpoints: the trigger (every document uploaded in one shot) and the latest result.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

import json
from typing import Annotated
from typing import TypeVar

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import Path
from fastapi import UploadFile
from pydantic import TypeAdapter
from pydantic import ValidationError

from src.adapters.kyc.models import PartyMockOverride
from src.ai.agents.anomaly_detection.schemas import DocumentIn
from src.ai.agents.anomaly_detection.schemas import DocumentMeta
from src.api.dependencies import get_case_service
from src.config.settings import Settings
from src.config.settings import get_anomaly_config
from src.config.settings import get_settings
from src.security.uploads import read_upload
from src.services.case_service import CaseService
from src.services.errors import InvalidInputError
from src.services.models import CASE_ID_PATTERN
from src.services.models import RunResult

router = APIRouter(prefix="/v1/cases", tags=["cases"])
CaseId = Annotated[
    str, Path(pattern=CASE_ID_PATTERN, description="Case / application number")
]
T = TypeVar("T")
_METAS: TypeAdapter[list[DocumentMeta]] = TypeAdapter(list[DocumentMeta])
_OVERRIDES: TypeAdapter[dict[str, PartyMockOverride]] = TypeAdapter(
    dict[str, PartyMockOverride]
)


def _parse(adapter: TypeAdapter[T], text: str, what: str) -> T:
    """Validate a JSON form field; messages never echo the values."""
    try:
        return adapter.validate_python(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        detail = (
            "; ".join(e["msg"] for e in exc.errors(include_input=False))
            if isinstance(exc, ValidationError)
            else "not valid JSON"
        )
        raise InvalidInputError(f"{what}: {detail}") from None


@router.post(
    "/{case_id}/trigger", response_model=RunResult, summary="Run the agents on a case"
)
def trigger(
    case_id: CaseId,
    files: Annotated[list[UploadFile], File(description="Every document of the case")],
    documents: Annotated[
        str, Form(description='JSON list: [{"file_name", "party_id", "doc_type"}]')
    ],
    service: Annotated[CaseService, Depends(get_case_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    mock_overrides: Annotated[str, Form(description="JSON object per party_id")] = "{}",
) -> RunResult:
    """Run the Orchestrator Agent (and through it the Anomaly Detection Agent).

    Args:
        case_id: The case; its lead must exist.
        files: Every document (format depends on the mode).
        documents: Who each file belongs to and its type, by file name.
        service: The case service.
        settings: Application settings (limits).
        mock_overrides: Forced mock third-party answers per person.

    Returns:
        The run result with the orchestrator summary and the full report.

    Raises:
        InvalidInputError: If a file or the metadata is not accepted.
    """
    config = get_anomaly_config()
    accepts = list(config["modes"][config["mode"]]["accepts"])
    metas = _parse(_METAS, documents, "documents")
    overrides = _parse(_OVERRIDES, mock_overrides or "{}", "mock_overrides")
    if not files or len(files) > settings.max_documents:
        raise InvalidInputError(f"send 1 to {settings.max_documents} files")
    by_name = {m.file_name: m for m in metas}
    if len(by_name) != len(metas) or len(files) != len(metas):
        raise InvalidInputError(
            "send exactly one documents entry per file, with unique names"
        )
    docs = []
    for file in files:
        meta = by_name.get(file.filename or "")
        if meta is None:
            raise InvalidInputError(
                f"{file.filename}: no documents entry for this file"
            )
        content = read_upload(file, accepts, settings.max_request_bytes)
        docs.append(DocumentIn(**meta.model_dump(), content=content))
    return service.trigger(case_id, docs, overrides)


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
