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
from src.config.settings import get_anomaly_config
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


def _model(prompt: Any, settings: Settings) -> str | None:
    """Effective model of a prompt name from the mode config (None when no LLM)."""
    if not prompt:
        return None
    configured = get_prompt_manager().config(str(prompt)).llm.model_id
    return settings.bedrock_model_id or configured


@router.get("/v1/info", summary="Mode, models, region and provider in use")
def info(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Return what the UI needs: the mode, the accepted files and the models.

    Args:
        settings: Application settings.

    Returns:
        Environment, region, mode, accepted file types, models and the provider.
    """
    config = get_anomaly_config()
    mode = config["modes"][config["mode"]]
    documents_prompt = mode.get("verification_prompt") or mode.get("extraction_prompt")
    return {
        "environment": settings.environment,
        "region": settings.aws_region,
        "mode": config["mode"],
        "mode_label": mode["label"],
        "accepts": mode["accepts"],
        "compared_by": "llm" if mode.get("verification_prompt") else "cross_verify",
        "application_form_model": _model(mode.get("application_form_prompt"), settings),
        "documents_model": _model(documents_prompt, settings),
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
