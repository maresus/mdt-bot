from __future__ import annotations

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


def _build_session_store() -> SessionStore:
    backend = (os.getenv("SESSION_BACKEND", "memory") or "memory").strip().lower()
    if backend != "memory":
        logger.warning(
            "SESSION_BACKEND=%s not yet enabled in phase 1, falling back to memory",
            backend,
        )
    return InMemorySessionStore()


_SESSION_STORE: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _SESSION_STORE
    if _SESSION_STORE is None:
        _SESSION_STORE = _build_session_store()
    return _SESSION_STORE

