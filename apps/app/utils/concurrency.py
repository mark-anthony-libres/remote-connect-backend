import inspect
from typing import Any, Callable

from fastapi.concurrency import run_in_threadpool


async def run_maybe_async(func: Callable, *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return await run_in_threadpool(func, *args, **kwargs)
