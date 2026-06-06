from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.observability import log_event
from app.data.decision_repo import DecisionRepository
from app.data.document_repo import DocumentRepository
from app.data.profile_repo import ProfileRepository
from app.llm.llm_factory import LlmBundle
from app.opportunity_engine.evaluation import evaluate_opportunities_with_trace
from app.opportunity_engine.repository import OpportunityRepository
from app.rag.ingestion import IngestionResult, ingest_document
from app.rag.retrieval import build_context, retrieve
from app.rag.vector_store import VectorStoreBundle
from app.reasoning.engine import GeneratedQueryResult, GeneratedRecommendations, generate_query_result, generate_recommendations


@dataclass(frozen=True)
class FinancialCopilotService:
    settings: Settings
    profiles: ProfileRepository
    documents: DocumentRepository
    decisions: DecisionRepository
    vector: VectorStoreBundle
    llm: LlmBundle
    opportunities: OpportunityRepository

    def upsert_profile(self, user_id: str, profile: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        if request_id:
            log_event("profile_upsert", request_id=request_id, user_id=user_id)
        return self.profiles.upsert(user_id=user_id, profile=profile)

    def get_profile(self, user_id: str, request_id: str | None = None) -> dict[str, Any] | None:
        profile = self.profiles.get(user_id=user_id)
        if request_id:
            log_event("profile_loaded", request_id=request_id, user_id=user_id, found=profile is not None)
        return profile

    def ingest(self, *, title: str, source: str | None, content: str, request_id: str | None = None) -> IngestionResult:
        if request_id:
            log_event("document_ingest_requested", request_id=request_id, title=title, source=source)
        return ingest_document(
            settings=self.settings,
            doc_repo=self.documents,
            vector=self.vector,
            title=title,
            source=source,
            content=content,
        )

    def query(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int | None,
        include_recommendations: bool,
        request_id: str | None = None,
    ) -> GeneratedQueryResult:
        profile = self.get_profile(user_id, request_id=request_id)
        if profile is None:
            raise KeyError("Profile not found")
        chunks = retrieve(
            settings=self.settings,
            doc_repo=self.documents,
            vector=self.vector,
            query=query,
            top_k=top_k,
        )
        context, citations = build_context(chunks)
        result = generate_query_result(
            llm=self.llm.llm,
            profile=profile,
            query=query,
            context=context,
            citations=citations,
            include_recommendations=include_recommendations,
        )
        if request_id:
            log_event(
                "query_answer_generated",
                request_id=request_id,
                user_id=user_id,
                include_recommendations=include_recommendations,
                fallback_used=result.fallback_used,
            )
        return result

    def recommendations(self, *, user_id: str, focus: str, request_id: str | None = None) -> GeneratedRecommendations:
        profile = self.get_profile(user_id, request_id=request_id)
        if profile is None:
            raise KeyError("Profile not found")
        chunks = retrieve(
            settings=self.settings,
            doc_repo=self.documents,
            vector=self.vector,
            query=f"macroeconomic context and market opportunities {focus}",
            top_k=self.settings.rag_top_k,
        )
        context, citations = build_context(chunks)
        country = (profile.get("country") or "US").upper()
        currency = (profile.get("preferences") or {}).get("currency") or "USD"
        opportunities = self.opportunities.filter(market_country=country, currency=str(currency).upper())
        if request_id:
            log_event(
                "opportunities_filtered",
                request_id=request_id,
                user_id=user_id,
                market_country=country,
                currency=str(currency).upper(),
                opportunity_count=len(opportunities),
            )
        matches, decision_trace = evaluate_opportunities_with_trace(profile=profile, opportunities=opportunities, max_results=3)
        result = generate_recommendations(
            llm=self.llm.llm,
            profile=profile,
            focus=focus,
            context=context,
            citations=citations,
            opportunity_matches=matches,
            opportunity_decision_trace=decision_trace,
        )
        decision_payload = {
            "recommendations": result.recommendations,
            "decision_context": result.decision_context,
            "mode": result.mode,
        }
        stored = self.decisions.create(user_id=user_id, decision=decision_payload)
        if request_id:
            log_event(
                "recommendation_generated",
                request_id=request_id,
                user_id=user_id,
                focus=focus,
                decision_id=stored["decision_id"],
            )
        result.decision_context["decision_id"] = stored["decision_id"]
        return result

    def list_decisions(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.decisions.list_for_user(user_id=user_id, limit=limit)

    def list_opportunities(self, *, market_country: str | None, currency: str | None) -> list[dict[str, Any]]:
        ops = self.opportunities.filter(market_country=market_country, currency=currency)
        return [op.model_dump() for op in ops]

    def match_opportunities(self, *, user_id: str) -> dict[str, Any]:
        profile = self.get_profile(user_id)
        if profile is None:
            raise KeyError("Profile not found")
        country = (profile.get("country") or "US").upper()
        currency = (profile.get("preferences") or {}).get("currency") or "USD"
        opportunities = self.opportunities.filter(market_country=country, currency=str(currency).upper())
        matches, trace = evaluate_opportunities_with_trace(profile=profile, opportunities=opportunities, max_results=5)
        return {
            "user_id": user_id,
            "market_country": country,
            "currency": str(currency).upper(),
            "matches": [
                {
                    "opportunity": m.opportunity.model_dump(),
                    "match_score": m.score,
                    "match_reason": m.match_reason,
                    "score_components": m.score_components,
                }
                for m in matches
            ],
            "decision_trace": trace.model_dump(),
        }
