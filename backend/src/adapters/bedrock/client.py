"""
File: client.py
Purpose: Bedrock models for Strands agents (timeouts, retries) and schema-bound extraction calls.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: boto3, botocore, strands-agents, pydantic
"""

import threading
from typing import TypeVar

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError
from botocore.exceptions import NoRegionError
from pydantic import BaseModel
from pydantic import SecretStr
from strands import Agent
from strands.models import BedrockModel
from strands.types.exceptions import EventLoopException
from strands.types.exceptions import MaxTokensReachedException
from strands.types.exceptions import ModelThrottledException
from strands.types.exceptions import StructuredOutputException

from src.config.settings import Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Errors that no retry can fix: the whole run stops with a clear message.
FATAL_AWS_CODES = frozenset(
    {
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
        "ExpiredToken",
        "AccessDeniedException",
        "InvalidClientTokenId",
        "ResourceNotFoundException",
    }
)
# Errors that fail one model call; the caller decides what that means.
MODEL_CALL_ERRORS: tuple[type[Exception], ...] = (
    BotoCoreError,
    ClientError,
    EventLoopException,
    MaxTokensReachedException,
    ModelThrottledException,
    StructuredOutputException,
    ValueError,
)


class BedrockUnavailableError(RuntimeError):
    """Bedrock refused the call for a reason no retry fixes (credentials, permission, model)."""


def find_fatal(exc: BaseException) -> str | None:
    """Walk an exception chain and explain it when no Bedrock call can succeed.

    Args:
        exc: The exception raised by a model call.

    Returns:
        A user-safe message for credential / permission / model errors, else None.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, NoCredentialsError | NoRegionError):
            return f"AWS credentials or region are not configured ({type(current).__name__})."
        if isinstance(current, ClientError):
            code = str(current.response.get("Error", {}).get("Code", ""))
            if code in FATAL_AWS_CODES:
                return (
                    f"Bedrock refused the request ({code}). Check the AWS "
                    "credentials, region and model access."
                )
        current = current.__cause__ or current.__context__
    return None


def _build_session(s: Settings) -> boto3.Session:
    """Create the boto3 session from the configured AWS keys and region.

    Args:
        s: Application settings.

    Returns:
        A boto3 session. Keys left unset fall back to the standard AWS chain.
    """

    def _val(secret: SecretStr | None) -> str | None:
        return secret.get_secret_value() if secret is not None else None

    return boto3.Session(
        aws_access_key_id=_val(s.aws_access_key_id),
        aws_secret_access_key=_val(s.aws_secret_access_key),
        aws_session_token=_val(s.aws_session_token),
        region_name=s.aws_region,
    )


class BedrockModels:
    """Creates one Strands ``BedrockModel`` per (model, temperature, max_tokens)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._models: dict[tuple[str, float, int], BedrockModel] = {}

    def model_id(self, configured: str) -> str:
        """Return the model to use: the ``BEDROCK_MODEL_ID`` override, else the prompt's.

        Args:
            configured: Model ID from the prompt config.

        Returns:
            The effective model ID.
        """
        return self._settings.bedrock_model_id or configured

    def get(self, model_id: str, temperature: float, max_tokens: int) -> BedrockModel:
        """Return a cached Bedrock model with connect/read timeouts and retries.

        Credentials come from the AWS access key, secret key and session token
        settings.

        Args:
            model_id: Model ID from the prompt config.
            temperature: Sampling temperature.
            max_tokens: Largest answer in tokens.

        Returns:
            The Strands Bedrock model.
        """
        key = (self.model_id(model_id), temperature, max_tokens)
        with self._lock:
            if key not in self._models:
                s = self._settings
                session = _build_session(s)
                self._models[key] = BedrockModel(
                    boto_session=session,
                    boto_client_config=BotoConfig(
                        connect_timeout=s.bedrock_connect_timeout_s,
                        read_timeout=s.bedrock_read_timeout_s,
                        retries={
                            "max_attempts": s.bedrock_max_attempts,
                            "mode": "standard",
                        },
                    ),
                    model_id=key[0],
                    # Qwen3 on ConverseStream drops the first tool-input delta
                    # ('{"'), so the tool JSON fails to parse. Use Converse.
                    streaming=False,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return self._models[key]


def extract_structured(
    model: BedrockModel,
    *,
    system_prompt: str,
    user_prompt: str,
    schema: type[SchemaT],
    name: str,
) -> SchemaT:
    """Make one Strands Agent call whose answer must fit ``schema``.

    Args:
        model: The Bedrock model.
        system_prompt: Rendered system prompt.
        user_prompt: Rendered user prompt.
        schema: Pydantic model the answer must match.
        name: Agent name (shows up in traces).

    Returns:
        The validated answer.

    Raises:
        BedrockUnavailableError: If Bedrock refuses the call for a fatal reason.
        StructuredOutputException: If the model gives no valid structured answer.
    """
    agent = Agent(
        model=model, system_prompt=system_prompt, callback_handler=None, name=name
    )
    try:
        result = agent(user_prompt, structured_output_model=schema)
    except MODEL_CALL_ERRORS as exc:
        fatal = find_fatal(exc)
        if fatal:
            raise BedrockUnavailableError(fatal) from exc
        raise
    answer = result.structured_output
    if not isinstance(answer, schema):
        raise StructuredOutputException("the model returned no structured output")
    return answer
