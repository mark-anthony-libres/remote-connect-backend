from apps.app.core.auth.access_token import is_impersonation_worker
from apps.app.modules.impersonation.service import impersonation_service
from apps.app.utils.decorators.analysis import analysis

_CLEANUP_INTERVAL_SECONDS = 5


@analysis(
    interval={"seconds": _CLEANUP_INTERVAL_SECONDS},
    name="Clean up a stale/orphaned impersonation Session",
    direct=True,
)
def cleanup_stale_impersonation_session():
    if not is_impersonation_worker():
        return
    impersonation_service.cleanup_stale_session()
