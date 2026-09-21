from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.app.core.settings import settings
from apps.app.core.logging import setup_logging
from apps.app.core.entities_discovery import EntitiesAutoDiscovery
from apps.app.core.middleware import request_id_middleware
from apps.app.core.errors import http_exception_handler, unhandled_exception_handler
from apps.monitor.controller import router as monitor_router
from apps.monitor.rate_limit import MonitorRateLimitMiddleware
from apps.monitor.websocket.gateway import (
    router as monitor_ws_router,
    start_invalidation_listener,
    stop_invalidation_listener,
)


@asynccontextmanager
async def monitor_lifespan(app: FastAPI):
    await start_invalidation_listener()
    try:
        yield
    finally:
        await stop_invalidation_listener()


def create_monitor_app() -> FastAPI:
    setup_logging()

    EntitiesAutoDiscovery().import_entity_modules()

    app = FastAPI(
        title="CentCom Monitor",
        version=settings.app_version,
        lifespan=monitor_lifespan,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.add_middleware(MonitorRateLimitMiddleware)

    app.middleware("http")(request_id_middleware)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(monitor_ws_router, prefix=settings.api_prefix)
    app.include_router(monitor_router, prefix=settings.api_prefix)

    return app


app = create_monitor_app()
