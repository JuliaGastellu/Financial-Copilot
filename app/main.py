from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.errors import ApiProblem
from app.api.v1 import build_v1_router
from app.auth.tokens import JwksCache, JwksSource, TokenVerifier, build_jwks_source
from app.core.config import Settings, settings as default_settings
from app.core.observability import RequestIdMiddleware, configure_logging, log_event
from app.db.engine import current_revision, head_revision
from app.opportunity_engine.models import InvestmentOpportunity
from app.schemas.models import HealthResponse, ReadyCheck
from app.services.container import build_container


def _rate_limit_key(request: Request) -> str:
    # Limito por cuenta cuando el token ya fue verificado; si no, por IP.
    return getattr(request.state, "rate_limit_key", None) or get_remote_address(request)


_limiter = Limiter(key_func=_rate_limit_key)

_NOTICE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Financial Copilot</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem;">
<h1>Financial Copilot</h1>
<p>La nueva experiencia web está en preparación. La API requiere iniciar sesión con un proveedor de identidad.</p>
<p>Información educativa; no es asesoramiento profesional.</p>
</body></html>"""


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        log_event(
            "request_completed",
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=getattr(request.state, "request_id", "unknown"),
            user_id=getattr(request.state, "user_id", None),
        )
        return response


def _build_verifier(app_settings: Settings, jwks_source: JwksSource | None) -> TokenVerifier | None:
    if not app_settings.oidc_issuer or not app_settings.oidc_audience:
        return None
    source = jwks_source or build_jwks_source(app_settings)
    cache = JwksCache(
        source,
        ttl_seconds=app_settings.jwks_cache_seconds,
        min_refresh_seconds=app_settings.jwks_min_refresh_seconds,
    )
    return TokenVerifier(app_settings, cache)


def create_app(settings_override: Settings | None = None, *, jwks_source: JwksSource | None = None) -> FastAPI:
    app_settings = settings_override or default_settings
    app_settings.validate_runtime()
    rate_limiting = app_settings.rate_limit_enabled and app_settings.environment != "test"

    def _limit(limit_str: str):
        if rate_limiting:
            return _limiter.limit(limit_str)
        return lambda f: f

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        app.state.container = build_container(app_settings)
        yield
        app.state.container.engine.dispose()

    production = app_settings.environment == "production"
    app = FastAPI(
        title="Financial Copilot API",
        description=(
            "Desarrollé una API para planificar ingresos, gastos, deudas y metas con reglas explícitas.\n\n"
            "Las rutas /v1 exigen un token de acceso OIDC; la cuenta sale del token, nunca de la URL ni del cuerpo.\n\n"
            "Presento información educativa. No ofrezco asesoramiento profesional."
        ),
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    app.state.settings = app_settings
    app.state.token_verifier = _build_verifier(app_settings, jwks_source)

    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Uso tokens en encabezado, no cookies: no habilito credenciales en CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # No devuelvo el valor recibido: puede no ser serializable (NaN) o contener datos personales.
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        log_event("request_failed", request_id=request_id, exc_type=type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})

    @app.middleware("http")
    async def auth_configured(request: Request, call_next: Any) -> Response:
        if request.url.path.startswith("/v1/") and app.state.token_verifier is None:
            return JSONResponse(status_code=503, content={"detail": "Authentication is not configured."})
        return await call_next(request)

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/ready", response_model=ReadyCheck, tags=["ops"])
    def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        container = app.state.container
        try:
            revision = current_revision(container.engine)
            head = head_revision(app_settings.resolved_database_url())
            checks["database"] = "ok" if revision == head else "error: migrations pending"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            container.vector.store.get(limit=1)
            checks["vector_store"] = "ok"
        except Exception as exc:
            checks["vector_store"] = f"error: {type(exc).__name__}"
        checks["authentication"] = "ok" if app.state.token_verifier is not None else "error: not configured"
        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if all_ok else 503, content={"status": "ready" if all_ok else "degraded", "checks": checks})

    @app.get("/opportunities", response_model=list[InvestmentOpportunity], tags=["catalog"])
    @_limit(app_settings.rate_limit_default)
    def list_opportunities(request: Request, market_country: str | None = None, currency: str | None = None) -> list[InvestmentOpportunity]:
        # Catálogo ilustrativo público: no contiene datos de personas.
        return app.state.container.opportunities.filter(market_country=market_country, currency=currency)

    app.include_router(build_v1_router(app_settings, _limit))

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(content=_NOTICE, status_code=200)

    return app


app = create_app()
