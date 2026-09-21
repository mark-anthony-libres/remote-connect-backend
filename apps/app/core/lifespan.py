
import logging, os
from apps.app.core.analysis_discovery import AnalysisJobDiscovery
from apps.app.utils.logger import Logger
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apps.app.utils.decorators.job_scheduler import cron_job_manager
from apps.app.core.cache_builder import RedisCacheManager
from apps.app.websocket.gateway import start_invalidation_listener, stop_invalidation_listener
from apps.app.core.settings import settings


logger = logging.getLogger("lifespan")


def _purge_celery_queue() -> None:
    try:
        from apps.app.celery_app import celery_app
        count = celery_app.control.purge()
        Logger.info(f"[lifespan] Purged {count} pending task(s) from broker queue")
    except Exception as exc:
        Logger.warning(f"[lifespan] Could not purge broker queue: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("startup")

    analysis_job = AnalysisJobDiscovery()
    analysis_job.import_analysis_modules()

    cron_job_manager.register_all_jobs()

    if settings.cache_disable:
        Logger.warning("Cache is disabled. Skipping Redis cache initialization.")
    else:
        redis_cache_manager = RedisCacheManager()
        await redis_cache_manager.initialize()

    await start_invalidation_listener()

    try:
        yield
    finally:
        await stop_invalidation_listener()
        scheduler = cron_job_manager.get_scheduler()
        if scheduler.running:
            scheduler.shutdown(wait=False)
        logger.info("shutdown")