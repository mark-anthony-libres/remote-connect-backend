from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt

from apps.app.core.settings import settings


class TokenError(Exception):
    pass


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def create_impersonation_token(
    target_user_id: int,
    admin_id: int,
    impersonation_id: str,
    ttl_seconds: int,
    admin_session_id,
) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": str(target_user_id),
        "exp": int(expires_at.timestamp()),
        "iat": int(now.timestamp()),
        "admin_id": str(admin_id),
        "impersonated": True,
        "impersonation_id": impersonation_id,
        "admin_session_id": str(admin_session_id),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
