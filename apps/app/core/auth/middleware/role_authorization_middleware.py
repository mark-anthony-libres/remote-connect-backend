import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from apps.app.core.auth.decorators import permission_denied_response
from apps.app.core.db import session_factory
from apps.app.core.settings import settings
from apps.app.modules.role.entities.role_group_entity import RoleGroupPermissionEnum
from apps.app.modules.role.repositories.role_group_repository import RoleGroupRepository
from apps.app.modules.role.repositories.role_repository import RoleRepository
from apps.app.core.auth.route_binding import resolve_group_id

_CHECKED_METHODS = {member.value for member in RoleGroupPermissionEnum}


class RoleAuthorizationMiddleware(BaseHTTPMiddleware):

    def __init__(
        self,
        app,
        admin_only_method_paths: list[tuple[str, "re.Pattern[str]"]],
        permission_exempt_method_paths: list[tuple[str, "re.Pattern[str]"]] = (),
        local_only_method_paths: list[tuple[str, "re.Pattern[str]"]] = (),
        permission_overrides: list[tuple[str, "re.Pattern[str]", str]] = (),
    ):
        super().__init__(app)
        self._admin_only_method_paths = admin_only_method_paths
        self._permission_exempt_method_paths = permission_exempt_method_paths
        self._local_only_method_paths = local_only_method_paths
        self._permission_overrides = permission_overrides

    async def dispatch(self, request: Request, call_next):
        if request.method not in _CHECKED_METHODS:
            return await call_next(request)

        normalized_path = request.url.path.rstrip("/") or "/"
        if (
            self._matches(self._admin_only_method_paths, request.method, normalized_path)
            or self._matches(self._permission_exempt_method_paths, request.method, normalized_path)
            or self._matches(self._local_only_method_paths, request.method, normalized_path)
        ):
            return await call_next(request)

        user = getattr(request.state, "user", None)
        if not user:
            return await call_next(request)

        custom_permissions = getattr(user, "custom_permissions", None)
        if custom_permissions is None and getattr(user, "effective_is_admin", False):
            return await call_next(request)

        group_id = resolve_group_id(request.url.path, settings.api_prefix or "")
        if not group_id:
            return await call_next(request)

        required_permission = self._required_permission(request.method, normalized_path)

        if custom_permissions is not None:
            granted_group_ids = {
                gid for gid, methods in custom_permissions.items()
                if required_permission in (methods or [])
            }
            if group_id not in granted_group_ids:
                return permission_denied_response(
                    request,
                    detail="You do not have permission to access this resource.",
                )
            return await call_next(request)

        role_id = getattr(user, "role_id", None) or self._get_default_role_id()
        if not role_id or not self._has_permission(role_id, group_id, required_permission):
            return permission_denied_response(
                request,
                detail="You do not have permission to access this resource.",
            )

        return await call_next(request)

    def _required_permission(self, method: str, path: str) -> str:
        for override_method, pattern, permission in self._permission_overrides:
            if override_method == method and pattern.match(path):
                return permission
        return method

    @staticmethod
    def _matches(method_paths: list[tuple[str, "re.Pattern[str]"]], method: str, path: str) -> bool:
        return any(m == method and pattern.match(path) for m, pattern in method_paths)

    @staticmethod
    def _has_permission(role_id: int, group_id: str, method: str) -> bool:
        from apps.app.core import db_guard

        with db_guard.exempt_one_checkout():
            db = session_factory()
            try:
                return RoleGroupRepository(db).has_permission(role_id, group_id, method)
            finally:
                db.close()

    @staticmethod
    def _get_default_role_id() -> int | None:
        from apps.app.core import db_guard

        with db_guard.exempt_one_checkout():
            db = session_factory()
            try:
                default_role = RoleRepository(db).get_default_role()
                return default_role.id if default_role else None
            finally:
                db.close()
