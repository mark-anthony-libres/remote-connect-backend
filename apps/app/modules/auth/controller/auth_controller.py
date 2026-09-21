import time

from fastapi import APIRouter, Request, Response, status, Depends, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
import os
from apps.app.utils import log_exception_with_traceback
from apps.app.core.auth.decorators import Public, Token
from apps.app.core.auth.access_token import clear_access_token_cookie
from apps.app.core.rate_limiting.account_lock import account_temporarily_locked_response
from apps.app.core.rate_limiting.user_blocking import user_block_store
from apps.app.core.request_logging.buffer import user_request_log_buffer
from apps.app.core import services
from apps.app.modules.auth.service import auth_service
from apps.app.modules.user.service import user_service

router = APIRouter(prefix="/auth")

@router.get("")
def welcome():
    return "welcome to auth services"



@router.get("/verify")
@Public()
async def verify(request: Request, token: str = Depends(Token)):
    if not token:
        log_exception_with_traceback(Exception("No token provided"), context="Token verification error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")

    try:
        impersonation_id_header = request.headers.get("x-impersonation-id")
        authenticated = services.call(
            auth_service.verify_token, token=token, impersonation_id_header=impersonation_id_header
        )
    except Exception as e:
        log_exception_with_traceback(e, context="Token verification failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    active_block = await user_block_store.get_active_block(authenticated.user.id)
    if active_block:
        retry_after = round(active_block["expires_at"] - time.time())
        return account_temporarily_locked_response(request.headers.get("origin"), retry_after)

    return {
        "valid": True,
    }


@router.post("/logout")
@Public()
async def logout(request: Request, response: Response, token: str = Depends(Token)):
    if not token:
        log_exception_with_traceback(Exception("No token provided"), context="Token verification error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")

    try:
        user_id, session_id = services.call(auth_service.logout, token=token)
    except Exception as e:
        log_exception_with_traceback(e, context="Logout failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to logout")

    try:
        await user_request_log_buffer.flush_endpoint_summary(user_id, session_id)
    except Exception as e:
        log_exception_with_traceback(e, context="Failed to flush request log buffer on logout")

    clear_access_token_cookie(response)
    return {
        "success": True,
        "message": "Logout successful",
    }


@router.post("/clear-session")
@Public()
async def clear_session(response: Response):
    clear_access_token_cookie(response)
    return {"success": True}
