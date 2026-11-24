"""
File: middleware.py
Purpose: Propagate an X-Correlation-ID header through logs and responses.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

import re
import uuid

from fastapi import Response

from src.utils.http_types import CallNext
from src.utils.http_types import HttpRequest
from src.utils.logging.logger import correlation_id

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


async def correlation_middleware(request: HttpRequest, call_next: CallNext) -> Response:
    """Reuse a well-formed incoming correlation ID or create a new one.

    Args:
        request: The incoming request.
        call_next: The next handler in the chain.

    Returns:
        The downstream response with the correlation ID header set.
    """
    incoming = request.headers.get(CORRELATION_HEADER, "")
    current_id = incoming if _VALID_ID.fullmatch(incoming) else str(uuid.uuid4())
    restore_point = correlation_id.set(current_id)
    try:
        response = await call_next(request)
    finally:
        correlation_id.reset(restore_point)
    response.headers[CORRELATION_HEADER] = current_id
    return response
