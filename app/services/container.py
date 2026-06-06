from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.data.document_repo import DocumentRepository
from app.data.decision_repo import DecisionRepository
from app.data.profile_repo import ProfileRepository
from app.data.sqlite import SqliteDb
from app.llm.llm_factory import LlmBundle, build_llm
from app.opportunity_engine.repository import OpportunityRepository
from app.rag.vector_store import VectorStoreBundle, build_vector_store


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    db: SqliteDb
    profiles: ProfileRepository
    documents: DocumentRepository
    decisions: DecisionRepository
    vector: VectorStoreBundle
    llm: LlmBundle
    opportunities: OpportunityRepository


def build_container(settings: Settings) -> AppContainer:
    db = SqliteDb(path=settings.resolved_sqlite_path())
    db.init_schema()
    vector = build_vector_store(settings)
    llm = build_llm(settings)
    opportunities = OpportunityRepository()
    return AppContainer(
        settings=settings,
        db=db,
        profiles=ProfileRepository(db=db),
        documents=DocumentRepository(db=db),
        decisions=DecisionRepository(db=db),
        vector=vector,
        llm=llm,
        opportunities=opportunities,
    )
