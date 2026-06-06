from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from app.core.config import Settings, settings as default_settings
from app.core.observability import RequestIdMiddleware, configure_logging, log_event
from app.opportunity_engine.models import InvestmentOpportunity
from app.schemas.models import (
    DecisionRecord,
    HealthResponse,
    IngestDocumentRequest,
    IngestDocumentResponse,
    ProfileResponse,
    ProfileUpsertRequest,
    QueryRequest,
    QueryResponse,
    ReadyCheck,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.container import AppContainer, build_container
from app.services.financial_copilot import FinancialCopilotService

_limiter = Limiter(key_func=get_remote_address)


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
        )
        return response


def _build_service(container: AppContainer) -> FinancialCopilotService:
    return FinancialCopilotService(
        settings=container.settings,
        profiles=container.profiles,
        documents=container.documents,
        decisions=container.decisions,
        vector=container.vector,
        llm=container.llm,
        opportunities=container.opportunities,
    )


def create_app(settings_override: Settings | None = None) -> FastAPI:
    app_settings = settings_override or default_settings
    rate_limiting = app_settings.rate_limit_enabled and app_settings.environment != "test"

    def _limit(limit_str: str):
        if rate_limiting:
            return _limiter.limit(limit_str)
        return lambda f: f

    ui_dir = (Path.cwd() / "public").resolve()
    if not (ui_dir / "index.html").exists():
        ui_dir = (Path(__file__).resolve().parent / "public").resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        app_settings.data_dir.mkdir(parents=True, exist_ok=True)
        container = build_container(app_settings)
        app.state.container = container
        app.state.service = _build_service(container)
        yield

    app = FastAPI(
        title="AI Financial Copilot",
        description=(
            "A deterministic financial copilot combining RAG-based contextual answering "
            "with auditable investment opportunity matching.\n\n"
            "**All recommendation logic is deterministic** — the same profile always produces "
            "the same recommendations.\n\n"
            "**Disclaimer:** This tool provides educational financial information only. "
            "It does not constitute financial advice."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        log_event("request_failed", request_id=request_id, error=str(exc), exc_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/ready", response_model=ReadyCheck, tags=["ops"])
    def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            container: AppContainer = app.state.container
            with container.db.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
        try:
            container = app.state.container
            container.vector.store.get(limit=1)
            checks["vector_store"] = "ok"
        except Exception as exc:
            checks["vector_store"] = f"error: {exc}"

        all_ok = all(v == "ok" for v in checks.values())
        status = "ready" if all_ok else "degraded"
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": status, "checks": checks},
        )

    @app.put("/profiles/{user_id}", response_model=ProfileResponse, tags=["profiles"])
    def upsert_profile(user_id: str, payload: ProfileUpsertRequest, request: Request) -> ProfileResponse:
        service: FinancialCopilotService = app.state.service
        profile = payload.profile.model_dump()
        if profile.get("user_id") != user_id:
            raise HTTPException(status_code=400, detail="Path user_id must match profile.user_id.")
        service.upsert_profile(user_id=user_id, profile=profile, request_id=request.state.request_id)
        stored = service.get_profile(user_id, request_id=request.state.request_id)
        if stored is None:
            raise HTTPException(status_code=500, detail="Failed to persist profile.")
        return ProfileResponse(profile=payload.profile)

    @app.get("/profiles/{user_id}", response_model=ProfileResponse, tags=["profiles"])
    def get_profile(user_id: str, request: Request) -> ProfileResponse:
        service: FinancialCopilotService = app.state.service
        stored = service.get_profile(user_id, request_id=request.state.request_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Profile not found.")
        return ProfileResponse(profile=_dict_to_profile(stored))

    @app.post("/context/ingest", response_model=IngestDocumentResponse, tags=["rag"])
    @_limit(app_settings.rate_limit_ingest)
    def ingest(payload: IngestDocumentRequest, request: Request) -> IngestDocumentResponse:
        service: FinancialCopilotService = app.state.service
        content = _extract_content(payload.content, payload.content_type)
        result = service.ingest(
            title=payload.title,
            source=payload.source,
            content=content,
            request_id=request.state.request_id,
        )
        return IngestDocumentResponse(doc_id=result.doc_id, chunks_indexed=result.chunks_indexed)

    @app.post("/query", response_model=QueryResponse, tags=["rag"])
    @_limit(app_settings.rate_limit_query)
    def query(payload: QueryRequest, request: Request) -> QueryResponse:
        service: FinancialCopilotService = app.state.service
        try:
            result = service.query(
                user_id=payload.user_id,
                query=payload.query,
                top_k=payload.top_k,
                include_recommendations=payload.include_recommendations,
                request_id=request.state.request_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Profile not found.")
        return QueryResponse(
            answer=result.answer,
            recommendations=result.recommendations,
            citations=result.citations,
            confidence=result.confidence,
            mode=result.mode,
            fallback_used=result.fallback_used,
            fallback_reason=result.fallback_reason,
        )

    @app.post("/recommendations", response_model=RecommendationResponse, tags=["recommendations"])
    @_limit(app_settings.rate_limit_recommendations)
    def recommendations(payload: RecommendationRequest, request: Request) -> RecommendationResponse:
        service: FinancialCopilotService = app.state.service
        try:
            result = service.recommendations(
                user_id=payload.user_id,
                focus=payload.focus,
                request_id=request.state.request_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Profile not found.")
        return RecommendationResponse(
            metrics=result.metrics,
            recommendations=result.recommendations,
            mode=result.mode,
            decision_context=result.decision_context,
        )

    @app.get("/opportunities", response_model=list[InvestmentOpportunity], tags=["opportunities"])
    def list_opportunities(
        market_country: str | None = None, currency: str | None = None
    ) -> list[InvestmentOpportunity]:
        service: FinancialCopilotService = app.state.service
        ops = service.opportunities.filter(market_country=market_country, currency=currency)
        return ops

    @app.get("/opportunities/match/{user_id}", tags=["opportunities"])
    def match_opportunities(user_id: str) -> dict:
        service: FinancialCopilotService = app.state.service
        try:
            return service.match_opportunities(user_id=user_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Profile not found.")

    @app.get("/decisions/{user_id}", response_model=list[DecisionRecord], tags=["decisions"])
    def list_decisions(user_id: str, limit: int = 50) -> list[dict]:
        service: FinancialCopilotService = app.state.service
        return service.list_decisions(user_id=user_id, limit=limit)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        return HTMLResponse(content=_read_ui_index(ui_dir), status_code=200)

    @app.get("/styles.css", include_in_schema=False)
    def styles_fallback():
        path = ui_dir / "styles.css"
        if path.exists():
            from fastapi.responses import FileResponse
            return FileResponse(path)
        raise HTTPException(status_code=404)

    @app.get("/app.js", include_in_schema=False)
    def js_fallback():
        path = ui_dir / "app.js"
        if path.exists():
            from fastapi.responses import FileResponse
            return FileResponse(path)
        raise HTTPException(status_code=404)

    return app


def _dict_to_profile(profile_dict: dict) -> "FinancialProfile":
    from app.schemas.models import FinancialProfile
    return FinancialProfile.model_validate(profile_dict)


def _extract_content(content: str, content_type: str) -> str:
    if content_type == "html":
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "head"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except ImportError:
            return content
    return content


def _read_ui_index(ui_dir: Path) -> str:
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        return "<html><body><h1>UI not found</h1><p>Missing public/index.html</p></body></html>"
    return index_path.read_text(encoding="utf-8")


app = create_app()
