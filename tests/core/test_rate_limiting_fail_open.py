from __future__ import annotations

import asyncio
import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from apps.app.core.rate_limiting.limiter import SlidingWindowRateLimiter
from apps.app.core.rate_limiting.middleware.path_rate_limit_middleware import _RenewingCooldown
from apps.app.core.rate_limiting.user_blocking import UserBlockStore


def _run(coro):
    return asyncio.run(coro)


class _StubScript:
    def __init__(self, *, result=None, raises: Exception | None = None):
        self._result = result
        self._raises = raises

    async def __call__(self, keys, args):
        if self._raises:
            raise self._raises
        return self._result


# --- SlidingWindowRateLimiter.try_record_hit ---

def test_try_record_hit_fails_open_on_connection_error(caplog):
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_hits=5)
    limiter._check_and_record = _StubScript(raises=RedisConnectionError("connection refused"))

    with caplog.at_level(logging.WARNING, logger="app"):
        allowed = _run(limiter.try_record_hit("some-key"))

    assert allowed is True
    assert any("RATE_LIMITER_DEGRADED" in r.message for r in caplog.records)


def test_try_record_hit_fails_open_on_timeout_error(caplog):
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_hits=5)
    limiter._check_and_record = _StubScript(raises=RedisTimeoutError("timed out"))

    with caplog.at_level(logging.WARNING, logger="app"):
        allowed = _run(limiter.try_record_hit("some-key"))

    assert allowed is True
    assert any("RATE_LIMITER_DEGRADED" in r.message for r in caplog.records)


def test_try_record_hit_allows_when_redis_healthy_and_under_limit():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_hits=5)
    limiter._check_and_record = _StubScript(result=1)

    assert _run(limiter.try_record_hit("some-key")) is True


def test_try_record_hit_denies_when_redis_healthy_and_over_limit():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_hits=5)
    limiter._check_and_record = _StubScript(result=0)

    assert _run(limiter.try_record_hit("some-key")) is False


def test_try_record_hit_does_not_swallow_unexpected_errors():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_hits=5)
    limiter._check_and_record = _StubScript(raises=ValueError("boom"))

    with pytest.raises(ValueError):
        _run(limiter.try_record_hit("some-key"))


# --- UserBlockStore.get_active_block ---

def test_get_active_block_fails_open_on_connection_error(monkeypatch, caplog):
    import apps.app.core.rate_limiting.user_blocking as user_blocking_module

    async def _raise(key):
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(user_blocking_module, "redis_get", _raise)
    store = UserBlockStore()

    with caplog.at_level(logging.WARNING, logger="app"):
        result = _run(store.get_active_block(user_id=123))

    assert result is None
    assert any("RATE_LIMITER_DEGRADED" in r.message for r in caplog.records)


def test_get_active_block_returns_block_when_redis_healthy(monkeypatch):
    import apps.app.core.rate_limiting.user_blocking as user_blocking_module

    async def _return_block(key):
        return b'{"reason": "test", "blocked_at": 1, "expires_at": 2}'

    monkeypatch.setattr(user_blocking_module, "redis_get", _return_block)
    store = UserBlockStore()

    result = _run(store.get_active_block(user_id=123))
    assert result == {"reason": "test", "blocked_at": 1, "expires_at": 2}


def test_get_active_block_does_not_swallow_unexpected_errors(monkeypatch):
    import apps.app.core.rate_limiting.user_blocking as user_blocking_module

    async def _raise(key):
        raise ValueError("boom")

    monkeypatch.setattr(user_blocking_module, "redis_get", _raise)
    store = UserBlockStore()

    with pytest.raises(ValueError):
        _run(store.get_active_block(user_id=123))


# --- _RenewingCooldown.is_active ---

def test_is_active_fails_open_on_connection_error(monkeypatch, caplog):
    import apps.app.core.rate_limiting.middleware.path_rate_limit_middleware as mod

    async def _raise(key):
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(mod, "redis_ttl", _raise)
    cooldown = _RenewingCooldown(cooldown_seconds=60)

    with caplog.at_level(logging.WARNING, logger="app"):
        result = _run(cooldown.is_active("some-cooldown-key"))

    assert result is False
    assert any("RATE_LIMITER_DEGRADED" in r.message for r in caplog.records)


def test_is_active_true_when_redis_healthy_and_ttl_positive(monkeypatch):
    import apps.app.core.rate_limiting.middleware.path_rate_limit_middleware as mod

    async def _ttl_positive(key):
        return 30

    monkeypatch.setattr(mod, "redis_ttl", _ttl_positive)
    cooldown = _RenewingCooldown(cooldown_seconds=60)

    assert _run(cooldown.is_active("some-cooldown-key")) is True


def test_is_active_false_when_redis_healthy_and_no_ttl(monkeypatch):
    import apps.app.core.rate_limiting.middleware.path_rate_limit_middleware as mod

    async def _ttl_expired(key):
        return -2

    monkeypatch.setattr(mod, "redis_ttl", _ttl_expired)
    cooldown = _RenewingCooldown(cooldown_seconds=60)

    assert _run(cooldown.is_active("some-cooldown-key")) is False


def test_is_active_does_not_swallow_unexpected_errors(monkeypatch):
    import apps.app.core.rate_limiting.middleware.path_rate_limit_middleware as mod

    async def _raise(key):
        raise ValueError("boom")

    monkeypatch.setattr(mod, "redis_ttl", _raise)
    cooldown = _RenewingCooldown(cooldown_seconds=60)

    with pytest.raises(ValueError):
        _run(cooldown.is_active("some-cooldown-key"))
