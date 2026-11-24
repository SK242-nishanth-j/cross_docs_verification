"""
File: settings.py
Purpose: Validated application settings loaded from environment variables.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: pydantic, pydantic-settings
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic import SecretStr
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

_BYTES_PER_MB = 1024 * 1024
_SRC_DIR = Path(__file__).resolve().parent.parent
_CROSS_VERIFY_CONFIG = (
    _SRC_DIR
    / "ai"
    / "agents"
    / "anomaly_detection"
    / "cross_verify"
    / "cross_verify_config.json"
)


class Settings(BaseSettings):
    """Application settings, validated at start-up.

    Values come from environment variables or, for local development, from
    ``.env`` and then ``.env.<environment>`` (for example ``.env.dev``); the
    latter wins, and real environment variables win over both. List values are
    JSON.

    AWS credentials come from ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``
    and ``AWS_SESSION_TOKEN``.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{os.getenv('ENVIRONMENT', 'dev')}"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "staging", "prod"] = "dev"
    service_name: str = "underwriting-copilot"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # AWS Bedrock. Model IDs and parameters live in src/ai/prompts/configs/*.yaml;
    # BEDROCK_MODEL_ID overrides the model of every prompt when set.
    aws_region: str = "ap-south-1"
    # AWS keys (keep them in the git-ignored .env / .env.<environment>).
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    bedrock_model_id: str | None = None
    bedrock_connect_timeout_s: int = Field(default=10, ge=1, le=60)
    bedrock_read_timeout_s: int = Field(default=180, ge=10, le=900)
    bedrock_max_attempts: int = Field(default=3, ge=1, le=10)

    # Processing.
    extraction_workers: int = Field(default=4, ge=1, le=16)
    document_max_ocr_chars: int = Field(default=40_000, ge=1_000, le=100_000)
    autofill_max_ocr_chars: int = Field(default=60_000, ge=5_000, le=100_000)
    max_documents: int = Field(default=60, ge=1, le=200)

    # Storage and configuration files.
    data_dir: Path = Path("storage")
    samples_dir: Path = Path("contracts/examples")
    anomaly_rules_path: Path = _SRC_DIR / "config" / "anomaly_rules.json"
    cross_verify_config_path: Path = _CROSS_VERIFY_CONFIG

    # HTTP.
    cors_allowed_origins: list[str] = Field(default_factory=list)
    rate_limit: str = Field(
        default="60/minute", pattern=r"^\d+/(second|minute|hour|day)$"
    )
    max_request_mb: int = Field(default=50, ge=1, le=500)

    @field_validator("bedrock_model_id")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        """Treat an empty value in an env file as "not set"."""
        if value is None or not value.strip():
            return None
        return value.strip()

    @field_validator(
        "aws_access_key_id", "aws_secret_access_key", "aws_session_token", mode="before"
    )
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        """Treat an empty AWS key in an env file as "not set".

        Args:
            value: Raw value from the environment.

        Returns:
            None for a blank string, the stripped string otherwise.
        """
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def max_request_bytes(self) -> int:
        """Return the largest accepted request body in bytes.

        Returns:
            ``max_request_mb`` in bytes.
        """
        return self.max_request_mb * _BYTES_PER_MB


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings.

    Returns:
        The validated settings instance.

    Raises:
        pydantic.ValidationError: If the environment holds invalid values.
    """
    return Settings()
