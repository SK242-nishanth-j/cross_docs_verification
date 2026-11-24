"""
File: errors.py
Purpose: Domain errors raised by the services and mapped to HTTP responses in main.py.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: stdlib only
"""


class ServiceError(Exception):
    """Base class of the service errors. Messages are safe to show to users."""


class CaseNotFoundError(ServiceError):
    """No lead has been created for this case yet."""


class ResultNotFoundError(ServiceError):
    """The case has no result yet."""


class InvalidCaseError(ServiceError):
    """The trigger does not fit the lead (for example an unknown party)."""


class InvalidInputError(ServiceError):
    """An uploaded file cannot be read in the configured mode."""


class AgentUnavailableError(ServiceError):
    """Bedrock refused the calls (credentials, permission or model access)."""
