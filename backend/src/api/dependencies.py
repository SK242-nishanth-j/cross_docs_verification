"""
File: dependencies.py
Purpose: Build the services once and hand them to the routers.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""

from functools import lru_cache

from src.adapters.bedrock.client import BedrockModels
from src.adapters.storage.case_store import CaseStore
from src.ai.agents.orchestrator import OrchestratorAgent
from src.ai.prompts.manager import get_prompt_manager
from src.config.settings import get_settings
from src.services.autofill_service import AutofillService
from src.services.case_service import CaseService


@lru_cache(maxsize=1)
def get_bedrock_models() -> BedrockModels:
    """Return the process-wide Bedrock model cache.

    Returns:
        The cached ``BedrockModels``.
    """
    return BedrockModels(get_settings())


@lru_cache(maxsize=1)
def get_case_service() -> CaseService:
    """Return the process-wide case service.

    Returns:
        The case service with its store and Orchestrator Agent.
    """
    store = CaseStore(get_settings().data_dir)
    return CaseService(
        store, OrchestratorAgent(get_prompt_manager(), get_bedrock_models())
    )


@lru_cache(maxsize=1)
def get_autofill_service() -> AutofillService:
    """Return the process-wide application-form auto-fill service.

    Returns:
        The auto-fill service.
    """
    return AutofillService(get_settings(), get_prompt_manager(), get_bedrock_models())
