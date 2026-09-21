from celery import Celery
from celery.signals import after_setup_logger, worker_process_init
import os

from apps.app.core.analysis_discovery import AnalysisJobDiscovery
from apps.app.core.logging import setup_worker_logging
from apps.app.core.settings import settings

celery_app = Celery(
    'app_tasks',
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend
)

celery_app.conf.broker_connection_retry_on_startup = True
celery_app.conf.broker_connection_max_retries = None
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_acks_late = True

celery_app.conf.broker_transport_options = {
    "retry_on_timeout": True,
    "socket_keepalive": True,
    "visibility_timeout": 60 * 60 * 24 * 2,
}

celery_app.conf.beat_schedule = {}
celery_app.conf.timezone = 'UTC'


@after_setup_logger.connect
def _mirror_worker_logs_to_file(**kwargs):
    setup_worker_logging()


@worker_process_init.connect
def _mirror_worker_child_process_logs_to_file(**kwargs):
    setup_worker_logging()


@celery_app.on_after_finalize.connect
def _register_analysis_tasks(sender, **kwargs):
    AnalysisJobDiscovery().import_analysis_modules()

if __name__ == "__main__":
    celery_app.start()
