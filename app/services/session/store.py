from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)


class SessionStore(Protocol):
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        ...

    def set(self, key: str, value: Dict[str, Any]) -> None:
        ...

    def delete(self, key: str) -> None:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._data.get(key)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


class RedisSessionStore:
    def __init__(self, redis_url: str, key_prefix: str, ttl_seconds: int) -> None:
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self._fallback = InMemorySessionStore()
        self._enabled = False
        self._client = None

        try:
            import redis  # type: ignore

            # Keep connect/read timeouts short so a bad Redis URL cannot stall requests.
            self._client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
                retry_on_timeout=False,
            )
            self._client.ping()
            self._enabled = True
            logger.info("Redis session store enabled")
        except Exception as exc:
            logger.warning("Redis unavailable, using in-memory session store fallback: %s", exc)

    def _redis_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self._enabled or self._client is None:
            return self._fallback.get(key)
        try:
            raw = self._client.get(self._redis_key(key))
            if not raw:
                return None
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
            return None
        except Exception as exc:
            logger.warning("Redis get failed, using fallback store: %s", exc)
            return self._fallback.get(key)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        if not self._enabled or self._client is None:
            self._fallback.set(key, value)
            return
        try:
            self._client.setex(self._redis_key(key), self.ttl_seconds, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Redis set failed, using fallback store: %s", exc)
            self._fallback.set(key, value)

    def delete(self, key: str) -> None:
        if not self._enabled or self._client is None:
            self._fallback.delete(key)
            return
        try:
            self._client.delete(self._redis_key(key))
        except Exception as exc:
            logger.warning("Redis delete failed, using fallback store: %s", exc)
            self._fallback.delete(key)


def _build_session_store() -> SessionStore:
    backend = (os.getenv("SESSION_BACKEND", "memory") or "memory").strip().lower()
    if backend == "redis":
        redis_url = (os.getenv("REDIS_URL", "") or "").strip()
        if not redis_url:
            logger.warning("SESSION_BACKEND=redis but REDIS_URL is empty; falling back to memory")
            return InMemorySessionStore()
        key_prefix = (os.getenv("SESSION_KEY_PREFIX", "health:center:session:") or "health:center:session:").strip()
        try:
            ttl_seconds = int((os.getenv("SESSION_TTL_SECONDS", "7200") or "7200").strip())
        except ValueError:
            ttl_seconds = 7200
        return RedisSessionStore(redis_url=redis_url, key_prefix=key_prefix, ttl_seconds=ttl_seconds)
    if backend != "memory":
        logger.warning("Unknown SESSION_BACKEND=%s; falling back to memory", backend)
    return InMemorySessionStore()


_SESSION_STORE: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _SESSION_STORE
    if _SESSION_STORE is None:
        _SESSION_STORE = _build_session_store()
    return _SESSION_STORE
