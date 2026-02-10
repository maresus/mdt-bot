from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.services.routing.nlp_utils import tokenize_meaningful


class ConversationTracker:
    """Track recent questions to detect loops with stop word filtering."""

    def __init__(self) -> None:
        self.recent_messages: dict[str, list[str]] = {}
        self.loop_count: dict[str, int] = {}

    def add_message(self, session_id: str, message: str) -> None:
        """Add message to tracking."""
        if session_id not in self.recent_messages:
            self.recent_messages[session_id] = []
        self.recent_messages[session_id].append(message.lower().strip())
        if len(self.recent_messages[session_id]) > 3:
            self.recent_messages[session_id].pop(0)

    def detect_loop(self, session_id: str, message: str) -> bool:
        """Detect if message is repeating (improved with stop word filtering)."""
        if session_id not in self.recent_messages:
            return False

        recent = self.recent_messages.get(session_id, [])
        if len(recent) < 2:
            return False

        msg_tokens = tokenize_meaningful(message)
        if len(msg_tokens) < 2:
            return False

        for prev_msg in recent[-3:]:
            prev_tokens = tokenize_meaningful(prev_msg)
            if len(prev_tokens) < 2:
                continue

            overlap = msg_tokens & prev_tokens
            overlap_ratio = len(overlap) / len(msg_tokens)
            if overlap_ratio > 0.85 and len(overlap) >= 2:
                self.loop_count[session_id] = self.loop_count.get(session_id, 0) + 1
                return True

        self.loop_count[session_id] = 0
        return False

    def get_loop_count(self, session_id: str) -> int:
        """Get current loop count."""
        return self.loop_count.get(session_id, 0)

    def reset_loop_count(self, session_id: str) -> None:
        """Reset loop counter."""
        self.loop_count[session_id] = 0


class SimpleCache:
    """Simple in-memory cache for LLM responses."""

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self.cache: dict[str, tuple[str, datetime]] = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    def get(self, query: str, context: str = "") -> Optional[str]:
        """Get cached response."""
        key = self._hash_key(query, context)
        if key in self.cache:
            response, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return response
            del self.cache[key]
        return None

    def set(self, query: str, response: str, context: str = "") -> None:
        """Cache response."""
        key = self._hash_key(query, context)
        self.cache[key] = (response, datetime.now())

    def _hash_key(self, query: str, context: str) -> str:
        """Generate cache key."""
        import hashlib

        combined = f"{query}:{context}"
        return hashlib.md5(combined.encode()).hexdigest()
