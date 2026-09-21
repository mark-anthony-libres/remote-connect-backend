import time
from datetime import datetime, timezone

from fastapi import Request
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware

from apps.app.core.request_logging.buffer import user_request_log_buffer
from apps.app.utils.logger import Logger

CACHE_STATUS_HEADER = "X-FastAPI-Cache"
CACHE_STATUS_HIT = "HIT"


class UserRequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            return await call_next(request)

        session_id = getattr(request.state, "session_id", None)

        time_received = datetime.now(timezone.utc)
        started_at = time.monotonic()

        response = await call_next(request)

        response_time = time.monotonic() - started_at
        end_response = datetime.now(timezone.utc)

        if session_id is not None:
            response.background = BackgroundTask(
                self._buffer_request_log,
                user_id=user_id,
                session_id=session_id,
                entry={
                    "endpoint": request.url.path.rstrip("/") or "/",
                    "time_received": time_received.isoformat(),
                    "end_response": end_response.isoformat(),
                    "response_time": response_time,
                    "is_cached": response.headers.get(CACHE_STATUS_HEADER) == CACHE_STATUS_HIT,
                },
            )

        return response

    @staticmethod
    async def _buffer_request_log(user_id, session_id, entry: dict):
        try:
            await user_request_log_buffer.record(user_id, session_id, entry)
        except Exception as exc:
            Logger.error(f"[UserRequestLogMiddleware] Failed to buffer request log: {exc}")
