import functools
import inspect
from typing import Callable

from fastapi import HTTPException

from apps.app.core.settings import settings
from apps.app.modules.monitor.services.monitor_session_service import is_session_token_valid


def require_monitor_token(func: Callable) -> Callable:
    def _check(kwargs: dict) -> None:
        if str(settings.environment).lower() == "local":
            return

        token = kwargs.get("x_monitor_token")
        if not token or not is_session_token_valid(token):
            raise HTTPException(status_code=401, detail="Invalid or expired monitor session")

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        _check(kwargs)
        return await func(*args, **kwargs)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        _check(kwargs)
        return func(*args, **kwargs)

    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
