"""
File: request_limits.py
Purpose: Reject oversized request bodies before they are read.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

from fastapi import Response
from fastapi import status
from fastapi.responses import JSONResponse

from src.config.settings import get_settings
from src.utils.http_types import CallNext
from src.utils.http_types import HttpRequest


async def request_size_middleware(
    request: HttpRequest, call_next: CallNext
) -> Response:
    """Return 413 when the declared Content-Length exceeds the configured limit.

    Args:
        request: The incoming request.
        call_next: The next handler in the chain.

    Returns:
        A 400 or 413 response for bad or oversized requests, else the
        downstream response.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Invalid Content-Length header."},
            )
        if size > get_settings().max_request_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={"detail": "Request body is too large."},
            )
    return await call_next(request)
