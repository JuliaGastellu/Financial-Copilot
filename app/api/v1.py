"""Rutas v1. Todas exigen un token válido; el propietario sale de `current_user`."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response

from app.auth.dependencies import current_user
from app.core.config import Settings
from app.api.errors import ApiProblem
from app.data.accounts import UserRecord
from app.data.planning import InvalidCursorError
from app.schemas.plans_v1 import (
    CurrentPlanV1,
    MonthlyReviewV1,
    Page,
    PlanCreateV1,
    PlanSummaryV1,
    PlanV1,
    ProgressCreateV1,
    ProgressEntryV1,
    ReproductionV1,
    ScenarioCreateV1,
    ScenarioSummaryV1,
    ScenarioV1,
)
from app.schemas.v1 import (
    DeletionResultV1,
    GoalInputV1,
    GoalV1,
    KnowledgeAnswerV1,
    KnowledgeQueryV1,
    MeV1,
    ProfileResponseV1,
    ProfileV1,
)
from app.services.accounts import AccountService, LimitExceededError, NotFoundError, goal_to_v1
from app.services.planning import ConflictError, PlanningService, ValidationProblem

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
    def create_goal(
        request: Request,
        response: Response,
        payload: GoalInputV1,
        user: UserRecord = Depends(current_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if idempotency_key is not None:
            from app.services.accounts import goal_values

            goal, replayed = _call(
                lambda: _planning(request).create_goal_idempotent(
                    user,
                    goal_values(payload.model_dump()),
                    payload.model_dump(mode="json"),
                    idempotency_key,
                    settings.max_goals_per_user,
                    _rid(request),
                )
            )
            _mark_replay(response, replayed)
            return goal_to_v1(goal)
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

    # ── Planes ──────────────────────────────────────────────────────────────

    @router.post("/plans", response_model=PlanV1, status_code=201, tags=["plans"])
    @limit(settings.rate_limit_plans)
    def create_plan(
        request: Request,
        response: Response,
        payload: PlanCreateV1,
        user: UserRecord = Depends(current_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> PlanV1:
        plan, replayed = _call(lambda: _planning(request).create_plan(user, payload.as_of, idempotency_key, _rid(request)))
        _mark_replay(response, replayed)
        return plan

    @router.get("/plans", response_model=Page[PlanSummaryV1], tags=["plans"])
    @limit(settings.rate_limit_default)
    def list_plans(
        request: Request,
        user: UserRecord = Depends(current_user),
        limit_: int = Query(20, ge=1, le=50, alias="limit"),
        cursor: str | None = Query(None, max_length=200),
    ) -> Page[PlanSummaryV1]:
        items, next_cursor = _call(lambda: _planning(request).list_plans(user, limit_, cursor))
        return Page[PlanSummaryV1](items=items, next_cursor=next_cursor)

    @router.get("/plans/current", response_model=CurrentPlanV1, tags=["plans"])
    @limit(settings.rate_limit_default)
    def current_plan(request: Request, user: UserRecord = Depends(current_user)) -> CurrentPlanV1:
        return _call(lambda: _planning(request).current_plan(user))

    @router.get("/plans/{plan_id}", response_model=PlanV1, tags=["plans"])
    @limit(settings.rate_limit_default)
    def get_plan(request: Request, plan_id: str, user: UserRecord = Depends(current_user)) -> PlanV1:
        return _call(lambda: _planning(request).get_plan(user, plan_id))

    @router.get("/plans/{plan_id}/reproduction", response_model=ReproductionV1, tags=["plans"])
    @limit(settings.rate_limit_plans)
    def reproduce_plan(request: Request, plan_id: str, user: UserRecord = Depends(current_user)) -> ReproductionV1:
        return _call(lambda: _planning(request).reproduce(user, plan_id))

    @router.delete("/plans/{plan_id}", status_code=204, tags=["plans"])
    @limit(settings.rate_limit_writes)
    def delete_plan(request: Request, plan_id: str, user: UserRecord = Depends(current_user)) -> Response:
        _call(lambda: _planning(request).delete_plan(user, plan_id, _rid(request)))
        return Response(status_code=204)

    # ── Escenarios ──────────────────────────────────────────────────────────

    @router.post("/scenarios", response_model=ScenarioV1, status_code=201, tags=["scenarios"])
    @limit(settings.rate_limit_plans)
    def create_scenario(
        request: Request,
        response: Response,
        payload: ScenarioCreateV1,
        user: UserRecord = Depends(current_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ScenarioV1:
        scenario, replayed = _call(
            lambda: _planning(request).create_scenario(user, payload.model_dump(mode="json"), idempotency_key, _rid(request))
        )
        _mark_replay(response, replayed)
        return scenario

    @router.get("/scenarios", response_model=Page[ScenarioSummaryV1], tags=["scenarios"])
    @limit(settings.rate_limit_default)
    def list_scenarios(
        request: Request,
        user: UserRecord = Depends(current_user),
        limit_: int = Query(20, ge=1, le=50, alias="limit"),
        cursor: str | None = Query(None, max_length=200),
        plan_id: str | None = Query(None, max_length=36),
    ) -> Page[ScenarioSummaryV1]:
        items, next_cursor = _call(lambda: _planning(request).list_scenarios(user, limit_, cursor, plan_id))
        return Page[ScenarioSummaryV1](items=items, next_cursor=next_cursor)

    @router.get("/scenarios/{scenario_id}", response_model=ScenarioV1, tags=["scenarios"])
    @limit(settings.rate_limit_default)
    def get_scenario(request: Request, scenario_id: str, user: UserRecord = Depends(current_user)) -> ScenarioV1:
        return _call(lambda: _planning(request).get_scenario(user, scenario_id))

    @router.post("/scenarios/{scenario_id}/adoption", response_model=PlanV1, status_code=201, tags=["scenarios"])
    @limit(settings.rate_limit_plans)
    def adopt_scenario(
        request: Request,
        response: Response,
        scenario_id: str,
        user: UserRecord = Depends(current_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> PlanV1:
        plan, replayed = _call(lambda: _planning(request).adopt(user, scenario_id, idempotency_key, _rid(request)))
        _mark_replay(response, replayed)
        return plan

    @router.delete("/scenarios/{scenario_id}", status_code=204, tags=["scenarios"])
    @limit(settings.rate_limit_writes)
    def delete_scenario(request: Request, scenario_id: str, user: UserRecord = Depends(current_user)) -> Response:
        _call(lambda: _planning(request).delete_scenario(user, scenario_id))
        return Response(status_code=204)

    # ── Avances y revisión mensual ──────────────────────────────────────────

    @router.post("/progress", response_model=ProgressEntryV1, status_code=201, tags=["progress"])
    @limit(settings.rate_limit_writes)
    def record_progress(
        request: Request,
        response: Response,
        payload: ProgressCreateV1,
        user: UserRecord = Depends(current_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ProgressEntryV1:
        entry, replayed = _call(
            lambda: _planning(request).record_progress(user, payload.model_dump(mode="json"), idempotency_key, _rid(request))
        )
        _mark_replay(response, replayed)
        return entry

    @router.get("/progress", response_model=Page[ProgressEntryV1], tags=["progress"])
    @limit(settings.rate_limit_default)
    def list_progress(
        request: Request,
        user: UserRecord = Depends(current_user),
        limit_: int = Query(20, ge=1, le=50, alias="limit"),
        cursor: str | None = Query(None, max_length=200),
        goal_id: str | None = Query(None, max_length=36),
        period: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    ) -> Page[ProgressEntryV1]:
        items, next_cursor = _call(lambda: _planning(request).list_progress(user, limit_, cursor, goal_id, period))
        return Page[ProgressEntryV1](items=items, next_cursor=next_cursor)

    @router.delete("/progress/{entry_id}", status_code=204, tags=["progress"])
    @limit(settings.rate_limit_writes)
    def delete_progress(request: Request, entry_id: str, user: UserRecord = Depends(current_user)) -> Response:
        _call(lambda: _planning(request).delete_progress(user, entry_id, _rid(request)))
        return Response(status_code=204)

    @router.get("/reviews/{period}", response_model=MonthlyReviewV1, tags=["progress"])
    @limit(settings.rate_limit_default)
    def monthly_review(
        request: Request,
        user: UserRecord = Depends(current_user),
        period: str = Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    ) -> MonthlyReviewV1:
        return _call(lambda: _planning(request).review(user, period))

    @router.post("/knowledge/query", response_model=KnowledgeAnswerV1, tags=["knowledge"])
    @limit(settings.rate_limit_query)
    def knowledge_query(request: Request, payload: KnowledgeQueryV1, user: UserRecord = Depends(current_user)) -> KnowledgeAnswerV1:
        result = request.app.state.container.knowledge.answer(payload.query, payload.top_k)
        return KnowledgeAnswerV1(**result)

    return router


def _planning(request: Request) -> PlanningService:
    return request.app.state.container.planning


def _mark_replay(response: Response, replayed: bool) -> None:
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"


_BAD_REQUEST_CODES = {"idempotency_key_required", "idempotency_key_invalid"}


def _call(fn: Callable[[], Any]) -> Any:
    """Traduzco errores de dominio a respuestas con un código estable para el cliente."""
    try:
        return fn()
    except NotFoundError:
        raise ApiProblem(404, "not_found", _NOT_FOUND)
    except ConflictError as exc:
        raise ApiProblem(409, exc.code, exc.message)
    except ValidationProblem as exc:
        raise ApiProblem(400 if exc.code in _BAD_REQUEST_CODES else 422, exc.code, exc.message)
    except InvalidCursorError:
        raise ApiProblem(400, "invalid_cursor", "The cursor is not valid. Request the first page again.")
