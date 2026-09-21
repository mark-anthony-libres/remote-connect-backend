import logging
from typing import Optional

from fastapi import Request, HTTPException, status

from apps.app.modules.auth.service.auth_service import ImpersonationInfo

logger = logging.getLogger("auth")


def get_current_user(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        logger.warning("No authenticated user on the request")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid access token")

    return user


def get_current_impersonation(request: Request) -> Optional[ImpersonationInfo]:
    return getattr(request.state, "impersonation", None)
