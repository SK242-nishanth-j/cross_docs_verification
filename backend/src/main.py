"""
File: main.py
Purpose: FastAPI application factory for the underwriting copilot (orchestrator + anomaly detection).
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: fastapi
"""

from fastapi import FastAPI
from fastapi import status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import cases
from src.api import leads
from src.api import system
from src.config.settings import get_settings
from src.security.rate_limit import create_rate_limit_middleware
from src.security.request_limits import request_size_middleware
from src.services.errors import AgentUnavailableError
from src.services.errors import CaseNotFoundError
from src.services.errors import InvalidCaseError
from src.services.errors import InvalidInputError
from src.services.errors import ResultNotFoundError
from src.utils.http_types import HttpRequest
from src.utils.logging.logger import get_logger
from src.utils.logging.middleware import CORRELATION_HEADER
from src.utils.logging.middleware import correlation_middleware

logger = get_logger(__name__)

_ERROR_STATUS: dict[type[Exception], int] = {
    CaseNotFoundError: status.HTTP_404_NOT_FOUND,
    ResultNotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidCaseError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidInputError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AgentUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _register_error_handlers(app: FastAPI) -> None:
    """Map domain errors to HTTP responses with user-safe messages."""

    async def handle(request: HttpRequest, exc: Exception) -> JSONResponse:
        code = _ERROR_STATUS[type(exc)]
        logger.warning(
            "request.failed",
            path=request.url.path,
            status=code,
            error_type=type(exc).__name__,
        )
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    for error in _ERROR_STATUS:
        app.add_exception_handler(error, handle)


def create_app() -> FastAPI:
    """Build the application with its middleware and routers.

    Returns:
        The configured FastAPI application.
    """
    settings = get_settings()
    is_prod = settings.environment == "prod"
    app = FastAPI(
        title="Underwriting Copilot: Orchestrator + Anomaly Detection",
        version="0.3.0",
        description=(
            "Application-form auto-fill, lead creation (base truth) and the trigger that "
            "runs the Orchestrator Agent and the Anomaly Detection Agent. Rate limit: "
            f"{settings.rate_limit} per client (the health probe is exempt)."
        ),
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )
    # The last middleware added is the outermost one, so CORS headers and the
    # correlation ID are present on every response, including errors.
    app.middleware("http")(request_size_middleware)
    app.middleware("http")(create_rate_limit_middleware(settings.rate_limit))
    app.middleware("http")(correlation_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", CORRELATION_HEADER],
        expose_headers=[CORRELATION_HEADER],
    )
    _register_error_handlers(app)
    app.include_router(system.router)
    app.include_router(leads.router)
    app.include_router(cases.router)
    logger.info(
        "app.started", environment=settings.environment, region=settings.aws_region
    )
    return app


app = create_app()
