"""Dependencia de FastAPI que deriva la cuenta del token verificado."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.auth.tokens import AuthenticationError
from app.core.observability import log_event
from app.data.accounts import UserRecord

_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="api"'}
_INVALID = {"WWW-Authenticate": 'Bearer realm="api", error="invalid_token"'}


def current_user(request: Request) -> UserRecord:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Missing access token.", headers=_CHALLENGE)
    verifier = request.app.state.token_verifier
    try:
        identity = verifier.verify(token.strip())
    except AuthenticationError as exc:
        log_event("auth_rejected", request_id=getattr(request.state, "request_id", None), reason=exc.reason)
        raise HTTPException(status_code=401, detail="Invalid access token.", headers=_INVALID) from exc
    user = request.app.state.container.users.get_or_create(identity.issuer, identity.subject)
    request.state.user_id = user.id
    request.state.rate_limit_key = f"user:{user.id}"
    return user
