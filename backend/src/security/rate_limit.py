"""
File: rate_limit.py
Purpose: Per-client sliding-window rate limiting applied to every endpoint.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

import math
import time
from collections import deque

from fastapi import Response
from fastapi import status
from fastapi.responses import JSONResponse

from src.utils.http_types import CallNext
from src.utils.http_types import HttpRequest
from src.utils.http_types import Middleware
from src.utils.logging.logger import get_logger

logger = get_logger(__name__)

EXEMPT_PATHS = frozenset({"/health"})
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_SWEEP_THRESHOLD = 10_000


def parse_rate_limit(value: str) -> tuple[int, int]:
    """Split a limit such as ``60/minute`` into a count and a window.

    Args:
        value: Limit in the form ``<count>/<second|minute|hour|day>``.

    Returns:
        ``(max_requests, window_seconds)``.

    Raises:
        ValueError: If the value is malformed.
    """
    count, _, unit = value.partition("/")
    if not count.isdigit() or int(count) < 1 or unit not in _UNIT_SECONDS:
        raise ValueError(f"Invalid rate limit: {value!r}")
    return int(count), _UNIT_SECONDS[unit]


class SlidingWindowRateLimiter:
    """Count requests per key in a moving time window (in memory, per process).

    It is only called from the event loop thread, so it needs no lock.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> float:
        """Record a request for ``key`` unless the limit is already reached.

        Args:
            key: Client identifier, normally the IP address.

        Returns:
            ``0.0`` when the request is allowed, otherwise the seconds until the
            client may retry. Refused requests are not counted.
        """
        now = time.monotonic()
        cutoff = now - self._window_seconds
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._max_requests:
            return max(hits[0] + self._window_seconds - now, 0.001)
        hits.append(now)
        if len(self._hits) > _SWEEP_THRESHOLD:
            self._sweep(cutoff)
        return 0.0

    def _sweep(self, cutoff: float) -> None:
        """Drop clients with no request inside the window to bound memory."""
        stale = [
            key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff
        ]
        for key in stale:
            del self._hits[key]


def create_rate_limit_middleware(rate_limit: str) -> Middleware:
    """Build a middleware that answers 429 once a client exceeds ``rate_limit``.

    Behind a reverse proxy every request shares the proxy's address, so run
    uvicorn with ``--proxy-headers`` to use the real client address.

    Args:
        rate_limit: Limit in the form ``<count>/<second|minute|hour|day>``.

    Returns:
        An async middleware function for ``app.middleware("http")``.
    """
    max_requests, window_seconds = parse_rate_limit(rate_limit)
    limiter = SlidingWindowRateLimiter(max_requests, window_seconds)

    async def rate_limit_middleware(
        request: HttpRequest, call_next: CallNext
    ) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        retry_after = limiter.check(client)
        if retry_after > 0:
            logger.warning("rate_limit.exceeded", path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Please retry shortly."},
                headers={"Retry-After": str(math.ceil(retry_after))},
            )
        return await call_next(request)

    return rate_limit_middleware
