import inspect
from functools import wraps
from fastapi import Request, Depends, status
from fastapi.responses import JSONResponse
from typing import Callable, Optional

from apps.app.core.auth.access_token import get_bearer_token
from apps.app.core.errors import json_error
from apps.app.modules.role.entities.role_group_entity import RoleGroupPermissionEnum
from apps.app.utils import is_local
from infra.groups import PERMISSION_OVERRIDE_KEY

IS_PUBLIC_KEY = "is_public"
IS_PASS_ON_INTERNAL_REQUESTS = "is_pass_on_internal_requests"
SILENT_EXCEPTION_EMAIL_KEY = "silent_exception_email"
IS_RATE_LIMITED_KEY = "is_rate_limited"
RATE_LIMIT_OVERRIDE_KEY = "rate_limit_override"
IS_ADMIN_ONLY_KEY = "is_admin_only"
IS_PERMISSION_EXEMPT_KEY = "is_permission_exempt"
IS_LOCAL_ONLY_KEY = "is_local_only"
IS_IMPERSONATION_AUTH_BYPASS_KEY = "is_impersonation_auth_bypass"

def ImpersonationAuthBypass():
    def decorator(func):
        setattr(func, IS_IMPERSONATION_AUTH_BYPASS_KEY, True)
        return func
    return decorator

def Public(rate_limit: bool = True):
    def decorator(func):
        setattr(func, IS_PUBLIC_KEY, True)
        if rate_limit:
            setattr(func, IS_RATE_LIMITED_KEY, True)
        return func
    return decorator

def RateLimit(max_requests: int = None, window_seconds: int = None):
    def decorator(func):
        setattr(func, IS_RATE_LIMITED_KEY, True)
        if max_requests is not None and window_seconds is not None:
            setattr(func, RATE_LIMIT_OVERRIDE_KEY, (window_seconds, max_requests))
        return func
    return decorator

def PassOnInternalRequest():
    def decorator(func):
        setattr(func, IS_PASS_ON_INTERNAL_REQUESTS, True)
        return func
    return decorator

def SilentExceptionEmail():
    def decorator(func):
        setattr(func, SILENT_EXCEPTION_EMAIL_KEY, True)
        return func
    return decorator

def CurrentUser(request: Request):
    return getattr(request.state, "user", None)

def Token(request: Request):
    return get_bearer_token(request)

def _extract_request(args: tuple, kwargs: dict) -> Optional[Request]:
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return None

def permission_denied_response(request: Optional[Request], detail: str = "Admin privileges are required to access this resource.") -> JSONResponse:
   
    request_id = getattr(request.state, "request_id", None) if request else None
    request_origin = request.headers.get("origin") if request else None
    return json_error(
        status_code=status.HTTP_403_FORBIDDEN,
        error="permission",
        detail=detail,
        request_id=request_id,
        request_origin=request_origin,
    )

def SkipGroupPermission():
    
    def decorator(func: Callable) -> Callable:
        setattr(func, IS_PERMISSION_EXEMPT_KEY, True)
        return func
    return decorator

def OverridePermission(permission: RoleGroupPermissionEnum):
    def decorator(func: Callable) -> Callable:
        setattr(func, PERMISSION_OVERRIDE_KEY, permission.value)
        return func
    return decorator

def can_view_archived(user, group_id: str) -> bool:
    if not user:
        return False

    custom_permissions = getattr(user, "custom_permissions", None)
    if custom_permissions is not None:
        return "PUT" in (custom_permissions.get(group_id) or [])

    if getattr(user, "effective_is_admin", False):
        return True

    from apps.app.core import db_guard
    from apps.app.core.db import session_factory
    from apps.app.modules.role.repositories.role_group_repository import RoleGroupRepository
    from apps.app.modules.role.repositories.role_repository import RoleRepository

    with db_guard.exempt_one_checkout():
        db = session_factory()
        try:
            role_id = getattr(user, "role_id", None)
            if not role_id:
                default_role = RoleRepository(db).get_default_role()
                role_id = default_role.id if default_role else None
            if not role_id:
                return False
            return RoleGroupRepository(db).has_permission(role_id, group_id, "PUT")
        finally:
            db.close()

def AdminOnlyAccess():
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            user = getattr(request.state, "user", None) if request else None
            if not user or not getattr(user, "effective_is_admin", False):
                return permission_denied_response(request)
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            user = getattr(request.state, "user", None) if request else None
            if not user or not getattr(user, "effective_is_admin", False):
                return permission_denied_response(request)
            return func(*args, **kwargs)

        chosen_wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
        setattr(chosen_wrapper, IS_ADMIN_ONLY_KEY, True)
        return chosen_wrapper
    return decorator

def LocalOnly():
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not is_local():
                request = _extract_request(args, kwargs)
                return permission_denied_response(
                    request,
                    detail="This endpoint is only available in the local environment.",
                )
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not is_local():
                request = _extract_request(args, kwargs)
                return permission_denied_response(
                    request,
                    detail="This endpoint is only available in the local environment.",
                )
            return func(*args, **kwargs)

        chosen_wrapper = async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
        setattr(chosen_wrapper, IS_LOCAL_ONLY_KEY, True)
        return chosen_wrapper
    return decorator
