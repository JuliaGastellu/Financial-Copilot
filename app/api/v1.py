"""Rutas v1. Todas exigen un token válido; el propietario sale de `current_user`."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.auth.dependencies import current_user
from app.core.config import Settings
from app.data.accounts import UserRecord
from app.schemas.v1 import (
    DeletionResultV1,
    GoalInputV1,
    GoalV1,
    KnowledgeAnswerV1,
    KnowledgeQueryV1,
    MeV1,
    PlanRecordV1,
    PlanRequestV1,
    PlanSummaryV1,
    ProfileResponseV1,
    ProfileV1,
)
from app.services.accounts import AccountService, LimitExceededError, NotFoundError, goal_to_v1

Limit = Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]]

# Uso el mismo mensaje para inexistente y ajeno: no revelo si el recurso existe.
_NOT_FOUND = "Not found."


def _service(request: Request) -> AccountService:
    return request.app.state.container.accounts


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def build_v1_router(settings: Settings, limit: Limit) -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(current_user)])

    @router.get("/me", response_model=MeV1, tags=["account"])
    @limit(settings.rate_limit_default)
    def me(request: Request, user: UserRecord = Depends(current_user)) -> MeV1:
        return MeV1(user_id=user.id, created_at=user.created_at)

    @router.get("/me/export", tags=["account"])
    @limit(settings.rate_limit_privacy)
    def export_account(request: Request, user: UserRecord = Depends(current_user)) -> Response:
        import json

        data = _service(request).export(user, _rid(request))
        body = json.dumps(data, default=str, ensure_ascii=False, sort_keys=True)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="account-export.json"', "Cache-Control": "no-store"},
        )

    @router.delete("/me", response_model=DeletionResultV1, tags=["account"])
    @limit(settings.rate_limit_privacy)
    def delete_account(request: Request, user: UserRecord = Depends(current_user)) -> DeletionResultV1:
        return DeletionResultV1(**_service(request).erase(user, _rid(request)))

    @router.get("/profile", response_model=ProfileResponseV1, tags=["profile"])
    @limit(settings.rate_limit_default)
    def get_profile(request: Request, user: UserRecord = Depends(current_user)) -> ProfileResponseV1:
        try:
            stored = _service(request).get_profile(user)
        except NotFoundError:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return ProfileResponseV1(profile=ProfileV1.model_validate(stored["data"]), updated_at=stored["updated_at"])

    @router.put("/profile", response_model=ProfileResponseV1, tags=["profile"])
    @limit(settings.rate_limit_writes)
    def put_profile(request: Request, payload: ProfileV1, user: UserRecord = Depends(current_user)) -> ProfileResponseV1:
        stored = _service(request).put_profile(user, payload.model_dump(mode="json"), _rid(request))
        return ProfileResponseV1(profile=ProfileV1.model_validate(stored["data"]), updated_at=stored["updated_at"])

    @router.get("/goals", response_model=list[GoalV1], tags=["goals"])
    @limit(settings.rate_limit_default)
    def list_goals(request: Request, user: UserRecord = Depends(current_user)) -> list[dict[str, Any]]:
        return [goal_to_v1(g) for g in _service(request).list_goals(user)]

    @router.post("/goals", response_model=GoalV1, status_code=201, tags=["goals"])
    @limit(settings.rate_limit_writes)
    def create_goal(request: Request, payload: GoalInputV1, user: UserRecord = Depends(current_user)) -> dict[str, Any]:
        try:
            goal = _service(request).create_goal(user, payload.model_dump(), _rid(request))
        except LimitExceededError:
            raise HTTPException(status_code=409, detail="Goal limit reached.")
        return goal_to_v1(goal)

    @router.get("/goals/{goal_id}", response_model=GoalV1, tags=["goals"])
    @limit(settings.rate_limit_default)
    def get_goal(request: Request, goal_id: str, user: UserRecord = Depends(current_user)) -> dict[str, Any]:
        try:
            return goal_to_v1(_service(request).get_goal(user, goal_id))
        except NotFoundError:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)

    @router.put("/goals/{goal_id}", response_model=GoalV1, tags=["goals"])
    @limit(settings.rate_limit_writes)
    def update_goal(request: Request, goal_id: str, payload: GoalInputV1, user: UserRecord = Depends(current_user)) -> dict[str, Any]:
        try:
            return goal_to_v1(_service(request).update_goal(user, goal_id, payload.model_dump(), _rid(request)))
        except NotFoundError:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)

    @router.delete("/goals/{goal_id}", status_code=204, tags=["goals"])
    @limit(settings.rate_limit_writes)
    def delete_goal(request: Request, goal_id: str, user: UserRecord = Depends(current_user)) -> Response:
        try:
            _service(request).delete_goal(user, goal_id, _rid(request))
        except NotFoundError:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return Response(status_code=204)

    @router.post("/plans", response_model=PlanRecordV1, status_code=201, tags=["plans"])
    @limit(settings.rate_limit_plans)
    def create_plan(request: Request, payload: PlanRequestV1, user: UserRecord = Depends(current_user)) -> PlanRecordV1:
        try:
            record = _service(request).create_plan(user, payload.as_of, _rid(request))
        except NotFoundError:
            raise HTTPException(status_code=409, detail="Create a profile before calculating a plan.")
        return _plan_record(record)

    @router.get("/plans", response_model=list[PlanSummaryV1], tags=["plans"])
    @limit(settings.rate_limit_default)
    def list_plans(request: Request, user: UserRecord = Depends(current_user), limit_: int = Query(20, ge=1, le=50, alias="limit")) -> list[dict[str, Any]]:
        return _service(request).list_plans(user, limit_)

    @router.get("/plans/{plan_id}", response_model=PlanRecordV1, tags=["plans"])
    @limit(settings.rate_limit_default)
    def get_plan(request: Request, plan_id: str, user: UserRecord = Depends(current_user)) -> PlanRecordV1:
        try:
            return _plan_record(_service(request).get_plan(user, plan_id))
        except NotFoundError:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)

    @router.delete("/plans/{plan_id}", status_code=204, tags=["plans"])
    @limit(settings.rate_limit_writes)
    def delete_plan(request: Request, plan_id: str, user: UserRecord = Depends(current_user)) -> Response:
        try:
            _service(request).delete_plan(user, plan_id, _rid(request))
        except NotFoundError:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return Response(status_code=204)

    @router.post("/knowledge/query", response_model=KnowledgeAnswerV1, tags=["knowledge"])
    @limit(settings.rate_limit_query)
    def knowledge_query(request: Request, payload: KnowledgeQueryV1, user: UserRecord = Depends(current_user)) -> KnowledgeAnswerV1:
        result = request.app.state.container.knowledge.answer(payload.query, payload.top_k)
        return KnowledgeAnswerV1(**result)

    return router


def _plan_record(record: dict[str, Any]) -> PlanRecordV1:
    return PlanRecordV1(
        id=record["id"],
        as_of=record["as_of"],
        policy_version=record["policy_version"],
        created_at=record["created_at"],
        plan=record["result"],
    )
