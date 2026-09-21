
from contextlib import contextmanager

from apps.app.core import services
from apps.app.modules.impersonation.service import impersonation_session_holder as holder
from apps.app.modules.impersonation.service.impersonation_service import (
    end_impersonation,
    handle_session_busy,
    verify_impersonation,
)


class _ImpersonationProvider:
    def begin(self, impersonation_id: str, admin_id):
        return verify_impersonation(impersonation_id, admin_id)

    @contextmanager
    def session_scope(self, active_impersonation):
        try:
            with holder.use_session(active_impersonation.impersonation_id) as (session, _started_at):
                yield session
        except TimeoutError:
            handle_session_busy()

    def fail(self, active_impersonation) -> None:
        end_impersonation(active_impersonation, reason="request_error")


def install() -> None:
    services.register_impersonation_provider(_ImpersonationProvider())
