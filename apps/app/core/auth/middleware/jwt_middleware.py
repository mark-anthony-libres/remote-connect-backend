import re

from apps.app.core.errors import json_error
from fastapi import HTTPException
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
import time

from apps.app.core.auth.access_token import get_bearer_token, is_impersonation_worker, set_access_token_cookie
from apps.app.core.db import session_factory
from apps.app.core.services import _current_admin_id, _current_impersonation_id
from apps.app.core.settings import settings
from apps.app.modules.auth.service import auth_service
from apps.app.modules.auth.service.auth_service import AuthenticatedSession
from apps.app.modules.okta.service.okta_service import OktaService
from apps.app.modules.user.repositories.user_sessions_resposity import UserSessionsRepository

SKIP_PATHS = frozenset({"/favicon.ico", "/robots.txt"})
SKIP_PREFIXES = ("/docs", "/openapi", "/redoc")

TOKEN_REFRESH_WINDOW_SECONDS = 120


class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        public_paths: set[str],
        impersonation_auth_bypass_method_paths: list[tuple[str, "re.Pattern[str]"]] = (),
    ):
        super().__init__(app)
        self._public_paths = public_paths
        self._impersonation_auth_bypass_method_paths = impersonation_auth_bypass_method_paths

    def _is_impersonation_auth_bypass(self, method: str, path: str) -> bool:
        return any(
            m == method and pattern.match(path)
            for m, pattern in self._impersonation_auth_bypass_method_paths
        )

    def _refresh_token_if_expiring_soon(self, response, exp: int, authenticated: AuthenticatedSession, current_token: str):
        remaining_seconds = exp - int(time.time())
        if remaining_seconds < TOKEN_REFRESH_WINDOW_SECONDS:
            new_token = OktaService.create_new_token(authenticated.user)["token"]
            db_session = session_factory()
            try:
                rotated = UserSessionsRepository(db_session).rotate_session_token(
                    authenticated.session.id,
                    new_token,
                    current_token,
                    settings.token_rotation_grace_seconds,
                )
            finally:
                db_session.close()
            if rotated:
                set_access_token_cookie(response, new_token)

        return response

    async def _dispatch_impersonation_worker(self, request: Request, call_next):
        impersonation_id_header = request.headers.get("x-impersonation-id")
        if not impersonation_id_header:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This worker only accepts impersonation requests: X-Impersonation-ID header is required.",
            )

        token = get_bearer_token(request)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This worker only accepts impersonation requests: an access token is required.",
            )

        try:
            authenticated = auth_service.authenticate(token, impersonation_id_header=impersonation_id_header)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired impersonation credentials.",
            )

        if authenticated.impersonation is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This worker only accepts impersonation requests.",
            )

        request.state.user_id = authenticated.user.id
        request.state.user = authenticated.user
        request.state.session_id = None
        request.state.impersonation = authenticated.impersonation

        admin_id_token = _current_admin_id.set(authenticated.impersonation.admin_id)
        impersonation_id_token = _current_impersonation_id.set(authenticated.impersonation.impersonation_id)
        try:
            return await call_next(request)
        finally:
            _current_admin_id.reset(admin_id_token)
            _current_impersonation_id.reset(impersonation_id_token)

    async def dispatch(self, request: Request, call_next):
        try:

            request.state.user_id = None

            if request.method == "OPTIONS":
                return await call_next(request)

            normalized_path = request.url.path.rstrip("/") or "/"
            bypasses_impersonation_gate = self._is_impersonation_auth_bypass(request.method, normalized_path)
            if is_impersonation_worker() and not bypasses_impersonation_gate:
                return await self._dispatch_impersonation_worker(request, call_next)

            url = request.url.path
            if url in SKIP_PATHS or url.startswith(SKIP_PREFIXES):
                return await call_next(request)

            normalized_url = url.rstrip("/") or "/"
            if normalized_url in self._public_paths:
                return await call_next(request)

            impersonation_id_header = request.headers.get("x-impersonation-id")
            if impersonation_id_header and not is_impersonation_worker():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Impersonation requests are not accepted on this worker.",
                )

            token = get_bearer_token(request)
            if not token:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")

            try:
                authenticated = auth_service.authenticate(
                    token, impersonation_id_header=impersonation_id_header
                )
            except Exception:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

            request.state.user_id = authenticated.user.id
            request.state.user = authenticated.user
            request.state.session_id = authenticated.session.id if authenticated.session else None
            request.state.impersonation = authenticated.impersonation

            if authenticated.impersonation:
                admin_id_token = _current_admin_id.set(authenticated.impersonation.admin_id)
                impersonation_id_token = _current_impersonation_id.set(
                    authenticated.impersonation.impersonation_id
                )
            else:
                admin_id_token = _current_admin_id.set(authenticated.user.id)
                impersonation_id_token = _current_impersonation_id.set(None)

            try:
                response = await call_next(request)
            finally:
                _current_admin_id.reset(admin_id_token)
                _current_impersonation_id.reset(impersonation_id_token)

            exp = authenticated.payload.get("exp")
            if exp and authenticated.session is not None:
                return self._refresh_token_if_expiring_soon(response, exp, authenticated, token)

            return response

        except HTTPException as exc:
            request_id = getattr(request.state, "request_id", None)
            error_type = "unauthorized" if exc.status_code == 401 else "http_error"
            return json_error(
                status_code=exc.status_code,
                error=error_type,
                detail=exc.detail,
                request_id=request_id,
                request_origin=request.headers.get("origin"),
            )
