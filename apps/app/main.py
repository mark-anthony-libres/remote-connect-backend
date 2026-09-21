from apps.app.core.controllers_discovery import ControllersAutoDiscovery
from fastapi import HTTPException
from apps.app.core.cache_builder import CacheDecodeError

import logging
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import compile_path

from apps.app.core.settings import settings
from apps.app.core.logging import setup_logging
from apps.app.core.lifespan import lifespan
from apps.app.core.middleware import cache_decode_error_middleware, request_id_middleware
from apps.app.core.errors import http_exception_handler, unhandled_exception_handler

from apps.app.core.auth.middleware.jwt_middleware import JWTAuthMiddleware
from apps.app.core.auth.middleware.role_authorization_middleware import RoleAuthorizationMiddleware
from apps.app.core.rate_limiting.middleware.path_rate_limit_middleware import PathRateLimitMiddleware
from apps.app.core.rate_limiting.middleware.user_rate_limit_middleware import UserRateLimitMiddleware
from apps.app.core.request_logging.middleware.user_request_log_middleware import UserRequestLogMiddleware
from apps.app.core.controllers_discovery import controllers
from apps.app.websocket.gateway import router as websocket_gateway_router
from apps.app.modules.device.websocket.device_gateway import router as device_gateway_router
from apps.app.core.auth.decorators import IS_ADMIN_ONLY_KEY, IS_IMPERSONATION_AUTH_BYPASS_KEY, IS_LOCAL_ONLY_KEY, IS_PERMISSION_EXEMPT_KEY, IS_PUBLIC_KEY, IS_RATE_LIMITED_KEY, PERMISSION_OVERRIDE_KEY, RATE_LIMIT_OVERRIDE_KEY

logger = logging.getLogger("app")

from fastapi.routing import APIRoute, APIRouter

def collect_decorated_paths(router: APIRouter, attribute: str, prefix: str = "") -> set[str]:
    matched: set[str] = set()

    def walk(routes, current_prefix: str):
        for route in routes:

            if isinstance(route, APIRoute):
                if getattr(route.endpoint, attribute, False):
                    matched.add((current_prefix + route.path).rstrip("/") or "/")

            elif hasattr(route, "original_router"):
                include = route.include_context

                next_prefix = current_prefix + (include.prefix or "")

                walk(route.original_router.routes, next_prefix)

    walk(router.routes, prefix)

    return matched


def collect_decorated_method_paths(router: APIRouter, attribute: str, prefix: str = "") -> list[tuple[str, "re.Pattern[str]"]]:
    matched: dict[tuple[str, str], "re.Pattern[str]"] = {}

    def walk(routes, current_prefix: str):
        for route in routes:

            if isinstance(route, APIRoute):
                if getattr(route.endpoint, attribute, False):
                    normalized_path = (current_prefix + route.path).rstrip("/") or "/"
                    path_regex, _, _ = compile_path(normalized_path)
                    for method in (route.methods or set()):
                        if method != "HEAD":
                            matched[(method, path_regex.pattern)] = path_regex

            elif hasattr(route, "original_router"):
                include = route.include_context

                next_prefix = current_prefix + (include.prefix or "")

                walk(route.original_router.routes, next_prefix)

    walk(router.routes, prefix)

    return [(method, pattern) for (method, _), pattern in matched.items()]


def collect_rate_limit_overrides(router: APIRouter, prefix: str = "") -> dict[str, tuple[int, int]]:
    overrides: dict[str, tuple[int, int]] = {}

    def walk(routes, current_prefix: str):
        for route in routes:

            if isinstance(route, APIRoute):
                override = getattr(route.endpoint, RATE_LIMIT_OVERRIDE_KEY, None)
                if override:
                    overrides[(current_prefix + route.path).rstrip("/") or "/"] = override

            elif hasattr(route, "original_router"):
                include = route.include_context

                next_prefix = current_prefix + (include.prefix or "")

                walk(route.original_router.routes, next_prefix)

    walk(router.routes, prefix)

    return overrides


def collect_permission_overrides(router: APIRouter, prefix: str = "") -> list[tuple[str, "re.Pattern[str]", str]]:
    matched: dict[tuple[str, str], tuple["re.Pattern[str]", str]] = {}

    def walk(routes, current_prefix: str):
        for route in routes:

            if isinstance(route, APIRoute):
                override = getattr(route.endpoint, PERMISSION_OVERRIDE_KEY, None)
                if override:
                    normalized_path = (current_prefix + route.path).rstrip("/") or "/"
                    path_regex, _, _ = compile_path(normalized_path)
                    for method in (route.methods or set()):
                        if method != "HEAD":
                            matched[(method, path_regex.pattern)] = (path_regex, override)

            elif hasattr(route, "original_router"):
                include = route.include_context

                next_prefix = current_prefix + (include.prefix or "")

                walk(route.original_router.routes, next_prefix)

    walk(router.routes, prefix)

    return [(method, pattern, permission) for (method, _), (pattern, permission) in matched.items()]


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        expose_headers=settings.cors_expose_headers
    )

    controllers_router = controllers.discover()

    app.include_router(websocket_gateway_router, prefix=settings.api_prefix)
    app.include_router(device_gateway_router, prefix=settings.api_prefix)
    app.include_router(controllers_router, prefix=settings.api_prefix)

    public_paths = collect_decorated_paths(
        controllers.router,
        IS_PUBLIC_KEY,
        settings.api_prefix,
    )
    rate_limited_paths = collect_decorated_paths(
        controllers.router,
        IS_RATE_LIMITED_KEY,
        settings.api_prefix,
    )
    rate_limit_overrides = collect_rate_limit_overrides(
        controllers.router,
        settings.api_prefix,
    )
    admin_only_method_paths = collect_decorated_method_paths(
        controllers.router,
        IS_ADMIN_ONLY_KEY,
        settings.api_prefix,
    )
    permission_exempt_method_paths = collect_decorated_method_paths(
        controllers.router,
        IS_PERMISSION_EXEMPT_KEY,
        settings.api_prefix,
    )
    local_only_method_paths = collect_decorated_method_paths(
        controllers.router,
        IS_LOCAL_ONLY_KEY,
        settings.api_prefix,
    )
    permission_overrides = collect_permission_overrides(
        controllers.router,
        settings.api_prefix,
    )
    impersonation_auth_bypass_method_paths = collect_decorated_method_paths(
        controllers.router,
        IS_IMPERSONATION_AUTH_BYPASS_KEY,
        settings.api_prefix,
    )

    app.add_middleware(
        RoleAuthorizationMiddleware,
        admin_only_method_paths,
        permission_exempt_method_paths,
        local_only_method_paths,
        permission_overrides,
    )
    app.add_middleware(UserRateLimitMiddleware)
    app.add_middleware(UserRequestLogMiddleware)
    app.add_middleware(
        JWTAuthMiddleware,
        public_paths,
        impersonation_auth_bypass_method_paths,
    )
    app.add_middleware(PathRateLimitMiddleware, rate_limited_paths, rate_limit_overrides)

    app.middleware("http")(request_id_middleware)
    app.middleware("http")(cache_decode_error_middleware)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.middleware("http")
    async def control_cache(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    logger.info("app_ready env=%s version=%s", settings.app_env, settings.app_version)
    return app


app = create_app()


