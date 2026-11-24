"""
File: system.py
Purpose: Liveness probe, runtime info and the example payloads for the UI.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

import json
from typing import Annotated
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Path
from fastapi import status

from src.ai.prompts.manager import get_prompt_manager
from src.config.settings import Settings
from src.config.settings import get_settings
from src.services.models import HealthStatus

router = APIRouter(tags=["system"])
SampleName = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
def health() -> HealthStatus:
    """Report that the service is running.

    Returns:
        ``{"status": "ok"}``.
    """
    return HealthStatus()


@router.get("/v1/info", summary="Model, region and provider in use")
def info(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Return what the UI shows in its header.

    Args:
        settings: Application settings.

    Returns:
        Environment, region, the extraction model and the third-party provider.
    """
    configured = get_prompt_manager().config("document_extraction").llm.model_id
    return {
        "environment": settings.environment,
        "region": settings.aws_region,
        "model_id": settings.bedrock_model_id or configured,
        "third_party": "mock",
    }


@router.get("/v1/samples", summary="Names of the example payloads")
def list_samples(settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    """List the example payloads.

    Args:
        settings: Application settings.

    Returns:
        Example names.
    """
    return sorted(p.stem for p in settings.samples_dir.glob("*.json"))


@router.get("/v1/samples/{name}", summary="One example payload")
def get_sample(
    name: SampleName, settings: Annotated[Settings, Depends(get_settings)]
) -> Any:
    """Return one example payload (synthetic data).

    Args:
        name: Example name.
        settings: Application settings.

    Returns:
        The example: case_id, lead, documents and mock_overrides.

    Raises:
        HTTPException: 404 if the example does not exist.
    """
    path = settings.samples_dir / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sample not found")
    return json.loads(path.read_text(encoding="utf-8"))
