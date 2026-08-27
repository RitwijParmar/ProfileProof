import hashlib
import hmac
import ipaddress
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .cache import TtlCache
from .config import Settings, get_settings
from .errors import ProfileProofError, RateLimitExceeded
from .metrics import Metrics
from .models import (
    CapabilitiesResponse,
    HealthResponse,
    Problem,
    ProfileResponse,
    ProviderCapability,
    ProviderName,
    ResolveRequest,
)
from .providers import (
    DemoProvider,
    LinkedInSessionProvider,
)
from .providers.base import ProfileProvider
from .rate_limit import SlidingWindowLimiter
from .service import ProfileService

logger = logging.getLogger("profileproof")
_LANDING_PAGE = Path(__file__).with_name("static").joinpath("index.html")
_STATIC_DIRECTORY = _LANDING_PAGE.parent
_APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data: https://media.licdn.com; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'; object-src 'none'"
)
_DOCS_CSP = (
    "default-src 'none'; script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; worker-src blob:; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)
_METRIC_ROUTES = frozenset(
    {
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
        "/healthz",
        "/readyz",
        "/metrics",
        "/v1/profiles/resolve",
        "/v1/capabilities",
    }
)


class RequestBodyLimitMiddleware:
    """Reject oversized streamed bodies before they can be buffered by the framework."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        if scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self._app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                await self._app(scope, receive, send)
                return
            body.extend(message.get("body", b""))
            if len(body) > self._max_body_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, replay_receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", str(uuid.uuid4()).encode()).decode(
            errors="replace"
        )[:128]
        response = JSONResponse(
            status_code=413,
            content={
                "type": "https://profileproof.dev/problems/body-too-large",
                "title": "Request body too large",
                "status": 413,
                "detail": f"The request body must not exceed {self._max_body_bytes} bytes.",
                "instance": scope.get("path", "unknown"),
                "request_id": request_id,
            },
            media_type="application/problem+json",
            headers={
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Cache-Control": "no-store",
            },
        )
        await response(scope, receive, send)


def _problem(
    request: Request, status: int, title: str, detail: str, problem_type: str
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    payload = Problem(
        type=problem_type,
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status,
        content=payload.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


class ApiMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings
        self._limiter = SlidingWindowLimiter(
            settings.rate_limit_requests, settings.rate_limit_window_seconds
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.monotonic()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id[:128]
        path = request.url.path
        response: Response
        try:
            if request.method in {"POST", "PUT", "PATCH"}:
                length = request.headers.get("content-length")
                try:
                    body_length = int(length) if length else 0
                except ValueError:
                    body_length = self._settings.max_body_bytes + 1
                if body_length > self._settings.max_body_bytes:
                    response = _problem(
                        request,
                        413,
                        "Request body too large",
                        f"The request body must not exceed {self._settings.max_body_bytes} bytes.",
                        "https://profileproof.dev/problems/body-too-large",
                    )
                    return await self._finalize(request, response, started)
            if path.startswith("/v1/"):
                allowed, remaining, retry_after = await self._limiter.allow(_client_key(request))
                if not allowed:
                    raise RateLimitExceeded("Too many requests from this client.")
                request.state.rate_limit_remaining = remaining
                if self._settings.api_key_sha256:
                    supplied = request.headers.get("x-api-key", "")
                    digest = hashlib.sha256(supplied.encode()).hexdigest()
                    if not hmac.compare_digest(digest, self._settings.api_key_sha256):
                        response = _problem(
                            request,
                            401,
                            "Invalid API key",
                            "A valid X-API-Key header is required.",
                            "https://profileproof.dev/problems/invalid-api-key",
                        )
                        return await self._finalize(request, response, started)
            response = await call_next(request)
        except RateLimitExceeded as error:
            response = _problem(
                request, error.status_code, error.title, error.detail, error.problem_type
            )
            response.headers["Retry-After"] = str(retry_after)
        return await self._finalize(request, response, started)

    async def _finalize(self, request: Request, response: Response, started: float) -> Response:
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path in {"/docs", "/redoc"} else _APP_CSP
        )
        if hasattr(request.state, "rate_limit_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
        duration_ms = (time.monotonic() - started) * 1000
        metrics: Metrics | None = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            route = request.url.path if request.url.path in _METRIC_ROUTES else "unmatched"
            await metrics.record_request(request.method, route, response.status_code)
        logger.info(
            "request_complete method=%s path=%s status=%s duration_ms=%.2f request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request.state.request_id,
        )
        return response


def create_app(
    settings: Settings | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            timeout=config.linkedin_timeout_seconds,
            follow_redirects=False,
            transport=upstream_transport,
        ) as upstream_client:
            linkedin_provider = LinkedInSessionProvider(
                upstream_client,
                config.linkedin_li_at.get_secret_value() if config.linkedin_li_at else None,
                (
                    config.linkedin_jsessionid.get_secret_value()
                    if config.linkedin_jsessionid
                    else None
                ),
                config.linkedin_calls_per_instance_per_day,
            )
            providers: dict[ProviderName, ProfileProvider] = {
                ProviderName.DEMO: DemoProvider(),
                ProviderName.LINKEDIN_SESSION: linkedin_provider,
            }
            app.state.service = ProfileService(
                providers=providers,
                cache=TtlCache(config.cache_ttl_seconds),
            )
            app.state.metrics = Metrics()
            app.state.linkedin_configured = linkedin_provider.configured
            yield

    application = FastAPI(
        title="ProfileProof API",
        version=__version__,
        summary="LinkedIn profile acquisition and structured normalization",
        description=(
            "Acquires authenticated LinkedIn profile data and normalizes it into a typed "
            "professional schema with explicit provenance and limitations."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    application.add_middleware(ApiMiddleware, settings=config)
    application.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=config.max_body_bytes)
    application.mount("/static", StaticFiles(directory=_STATIC_DIRECTORY), name="static")

    @application.exception_handler(ProfileProofError)
    async def profileproof_error(request: Request, error: ProfileProofError) -> JSONResponse:
        return _problem(request, error.status_code, error.title, error.detail, error.problem_type)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        )
        return _problem(
            request,
            422,
            "Request validation failed",
            details,
            "https://profileproof.dev/problems/validation",
        )

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing() -> HTMLResponse:
        return HTMLResponse(_LANDING_PAGE.read_text(encoding="utf-8"))

    @application.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    async def swagger_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=application.openapi_url or "/openapi.json",
            title=f"{application.title} - Swagger UI",
            swagger_js_url=(
                "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.14/swagger-ui-bundle.js"
            ),
            swagger_css_url=("https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.14/swagger-ui.css"),
        )

    @application.get("/redoc", response_class=HTMLResponse, include_in_schema=False)
    async def redoc_docs() -> HTMLResponse:
        return get_redoc_html(
            openapi_url=application.openapi_url or "/openapi.json",
            title=f"{application.title} - ReDoc",
            redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2.5.3/bundles/redoc.standalone.js",
        )

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__, environment=config.environment)

    application.add_api_route("/healthz", health, methods=["GET"], include_in_schema=False)

    @application.get("/readyz", response_model=HealthResponse, tags=["operations"])
    async def readiness() -> HealthResponse:
        return HealthResponse(status="ready", version=__version__, environment=config.environment)

    @application.get("/metrics", response_class=PlainTextResponse, tags=["operations"])
    async def metrics(request: Request) -> PlainTextResponse:
        return PlainTextResponse(await request.app.state.metrics.render())

    @application.get("/v1/capabilities", response_model=CapabilitiesResponse, tags=["operations"])
    async def capabilities(request: Request) -> CapabilitiesResponse:
        return CapabilitiesResponse(
            providers=[
                ProviderCapability(
                    name=ProviderName.LINKEDIN_SESSION,
                    configured=bool(request.app.state.linkedin_configured),
                    real_data=True,
                    description="Authenticated LinkedIn profile-page acquisition.",
                ),
                ProviderCapability(
                    name=ProviderName.DEMO,
                    configured=config.enable_demo_provider,
                    real_data=False,
                    description="Deterministic synthetic integration fixture.",
                ),
            ]
        )

    @application.post(
        "/v1/profiles/resolve",
        response_model=ProfileResponse,
        response_model_exclude_none=True,
        tags=["profiles"],
        responses={401: {"model": Problem}, 422: {"model": Problem}, 424: {"model": Problem}},
    )
    async def resolve_profile(
        request: Request,
        payload: ResolveRequest,
        authorization: str | None = Header(default=None),
    ) -> ProfileResponse:
        service: ProfileService = request.app.state.service
        try:
            result = await service.resolve(payload, request.state.request_id, authorization)
        except ProfileProofError:
            await request.app.state.metrics.record_provider(payload.provider, "error")
            raise
        await request.app.state.metrics.record_provider(payload.provider, "success")
        return result

    return application


app = create_app()
