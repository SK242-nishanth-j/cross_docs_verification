"""
File: http_types.py
Purpose: Shared type aliases for HTTP middleware signatures.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import Request
from fastapi import Response
from starlette.datastructures import State

# Request is generic over its state type. Spelling the parameter out keeps
# mypy --strict satisfied on the pinned 1.7.1.
HttpRequest = Request[State]
CallNext = Callable[[HttpRequest], Awaitable[Response]]
Middleware = Callable[[HttpRequest, CallNext], Awaitable[Response]]
