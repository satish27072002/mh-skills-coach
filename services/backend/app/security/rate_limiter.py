"""
In-memory sliding-window rate limiter for the /chat endpoint.

Limits per session ID (cookie) with IP fallback.
Default: 10 requests per 60 seconds per session/IP.

Usage in main.py:
    from app.security.rate_limiter import RateLimiter, RateLimitExceeded
    from app.config import settings

    _rate_limiter = RateLimiter(
        max_requests=settings.rate_limit_chat_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    @app.post("/chat")
    def chat(payload: ChatRequest, request: Request, response: Response, ...):
        client_key = request.cookies.get(settings.session_cookie_name) or request.client.host
        try:
            _rate_limiter.check(client_key)
        except RateLimitExceeded:
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")
        ...
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque


class RateLimitExceeded(Exception):
    """Raised when a client exceeds the allowed request rate."""

    def __init__(self, client_key: str, limit: int, window: int) -> None:
        self.client_key = client_key
        self.limit = limit
        self.window = window
        super().__init__(
            f"Rate limit exceeded for {client_key!r}: "
            f"max {limit} requests per {window}s"
        )


class RateLimiter:
    """Thread-safe sliding-window rate limiter using an in-memory dict.

    Each unique client key gets a deque of request timestamps.
    On each call to check(), timestamps older than the window are removed.
    If the remaining count >= max_requests, RateLimitExceeded is raised.

    Note: This is an in-process store — it resets on restart and does not
    share state across multiple worker processes. For production with multiple
    workers, migrate to Redis with the same sliding-window algorithm.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._max_requests = max_requests
        self._window = window_seconds
        self._store: dict[str, Deque[float]] = {}
        self._lock = Lock()

    def check(self, client_key: str) -> None:
        """Check the rate limit for a client.

        Args:
            client_key: a session ID or IP address string

        Raises:
            RateLimitExceeded: if the client has exceeded the rate limit
        """
        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            if client_key not in self._store:
                self._store[client_key] = deque()

            window = self._store[client_key]

            # Remove timestamps outside the rolling window
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self._max_requests:
                raise RateLimitExceeded(
                    client_key=client_key,
                    limit=self._max_requests,
                    window=self._window,
                )

            window.append(now)

    def remaining(self, client_key: str) -> int:
        """Return how many requests the client has left in the current window."""
        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            if client_key not in self._store:
                return self._max_requests
            window = self._store[client_key]
            current = sum(1 for ts in window if ts >= cutoff)
            return max(0, self._max_requests - current)

    def reset(self, client_key: str) -> None:
        """Clear rate limit state for a client (useful in tests)."""
        with self._lock:
            self._store.pop(client_key, None)

    def purge_expired(self) -> int:
        """Remove all expired entries to free memory. Returns count removed."""
        now = time.monotonic()
        cutoff = now - self._window
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, dq in self._store.items()
                if not dq or dq[-1] < cutoff
            ]
            for key in expired_keys:
                del self._store[key]
                removed += 1
        return removed
