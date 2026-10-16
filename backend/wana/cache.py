"""Redis-backed rate limits, idempotency keys and locks, with an in-process fallback.

The fallback keeps a laptop or the test suite working with no Redis. With several API processes it would
not be shared, so production always sets REDIS_URL.
"""
from __future__ import annotations

import json
import threading
import time

from .obs import DEPENDENCY_UP, BusinessError, PlatformError, UserError
from .settings import settings


class _Memory:
    def __init__(self):
        self._d: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.Lock()

    def _live(self, k):
        v = self._d.get(k)
        if v and v[1] is not None and v[1] < time.time():
            del self._d[k]
            return None
        return v

    def get(self, k):
        with self._lock:
            v = self._live(k)
            return v[0] if v else None

    def set(self, k, val, ex=None, nx=False):
        with self._lock:
            if nx and self._live(k):
                return None
            self._d[k] = (str(val), time.time() + ex if ex else None)
            return True

    def incr(self, k):
        with self._lock:
            v = self._live(k)
            n = int(v[0]) + 1 if v else 1
            self._d[k] = (str(n), v[1] if v else None)
            return n

    def expire(self, k, s):
        with self._lock:
            v = self._live(k)
            if v:
                self._d[k] = (v[0], time.time() + s)

    def ttl(self, k):
        v = self._live(k)
        return int(v[1] - time.time()) if v and v[1] else -1

    def delete(self, k):
        with self._lock:
            self._d.pop(k, None)

    def ping(self):
        return True


_client = None


def client():
    global _client
    if _client is None:
        if settings.redis_url:
            import redis
            _client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2,
                                           socket_connect_timeout=2, health_check_interval=30)
        else:
            _client = _Memory()
    return _client


def _call(fn, *a, **kw):
    try:
        out = getattr(client(), fn)(*a, **kw)
        DEPENDENCY_UP.labels("redis").set(1)
        return out
    except Exception as e:  # noqa: BLE001  (redis.ConnectionError and friends)
        DEPENDENCY_UP.labels("redis").set(0)
        raise PlatformError("A storage service is not answering. Please try again shortly.", "redis_down") from e


def rate_limit(key: str, limit: int, window_s: int, what: str = "requests"):
    """Fixed-window limit. Raises a user error (429) with Retry-After when over."""
    k = f"rl:{key}:{int(time.time() // window_s)}"
    n = _call("incr", k)
    if n == 1:
        _call("expire", k, window_s)
    if n > limit:
        retry = window_s - int(time.time() % window_s)
        raise UserError(f"Too many {what}. Try again in {max(1, retry // 60) if retry >= 60 else retry} "
                        f"{'minute(s)' if retry >= 60 else 'second(s)'}.", "rate_limited", 429,
                        headers={"Retry-After": str(retry)})


def idempotent_get(scope: str, key: str):
    v = _call("get", f"idem:{scope}:{key}")
    return json.loads(v) if v else None


def idempotent_put(scope: str, key: str, value, ttl=24 * 3600):
    _call("set", f"idem:{scope}:{key}", json.dumps(value), ex=ttl)


class Lock:
    """Short critical sections across processes (e.g. one retrain at a time)."""

    def __init__(self, name: str, ttl: int = 600, busy_message: str = "Another update is already running."):
        self.k, self.ttl, self.msg = f"lock:{name}", ttl, busy_message

    def __enter__(self):
        if not _call("set", self.k, "1", ex=self.ttl, nx=True):
            raise BusinessError(self.msg, "busy")
        return self

    def __exit__(self, *exc):
        _call("delete", self.k)


def ping() -> bool:
    try:
        return bool(_call("ping"))
    except PlatformError:
        return False
