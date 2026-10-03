from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from app.core.config import Settings
from app.data.accounts import AuditRepository, GoalRepository, PlanRepository, ProfileRepository, UserRepository
from app.data.documents import PublicCorpusRepository
from app.data.privacy import PrivacyRepository
from app.db.engine import build_engine, upgrade
from app.opportunity_engine.repository import OpportunityRepository
from app.rag.vector_store import VectorStoreBundle, build_vector_store
from app.services.accounts import AccountService, KnowledgeService


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    engine: Engine
    users: UserRepository
    corpus: PublicCorpusRepository
    vector: VectorStoreBundle
    opportunities: OpportunityRepository
    accounts: AccountService
    knowledge: KnowledgeService
    privacy: PrivacyRepository


def build_container(settings: Settings) -> AppContainer:
    url = settings.resolved_database_url()
    if settings.auto_migrate:
        upgrade(url)
    engine = build_engine(url)
    vector = build_vector_store(settings)
    corpus = PublicCorpusRepository(engine)
    privacy = PrivacyRepository(engine, settings)
    accounts = AccountService(
        settings=settings,
        profiles=ProfileRepository(engine),
        goals=GoalRepository(engine),
        plans=PlanRepository(engine),
        audit=AuditRepository(engine),
        privacy=privacy,
    )
    return AppContainer(
        settings=settings,
        engine=engine,
        users=UserRepository(engine),
        corpus=corpus,
        vector=vector,
        opportunities=OpportunityRepository(),
        accounts=accounts,
        knowledge=KnowledgeService(settings=settings, corpus=corpus, vector=vector),
        privacy=privacy,
    )
