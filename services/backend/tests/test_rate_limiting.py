"""
Tests for the /chat rate limiter.

Verifies:
- 10 requests within 60 seconds are allowed (HTTP 200)
- The 11th request within 60 seconds returns HTTP 429
- Different session IDs have completely separate rate limit buckets
- The rate limiter resets correctly between tests (via conftest autouse fixture)
"""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app, _rate_limiter
from app.models import User


ORIGINAL_DATABASE_URL = str(db.engine.url)


# ---------------------------------------------------------------------------
# DB fixture — mirrors pattern used in other test files
# ---------------------------------------------------------------------------
@pytest.fixture()
def rl_db():
    db.reset_engine("sqlite+pysqlite:///./test_rate_limiting.db")
    db.init_db()
    with db.SessionLocal() as session:
        session.query(User).delete()
        session.commit()
    yield
    db.reset_engine(ORIGINAL_DATABASE_URL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_chat_request(client: TestClient, message: str = "I feel stressed") -> int:
    """POST /chat and return the HTTP status code."""
    response = client.post("/chat", json={"message": message})
    return response.status_code


def _monkeypatch_run_agent(monkeypatch) -> None:
    """Stub run_agent so tests don't need a real LLM or DB."""
    monkeypatch.setattr(
        "app.main.run_agent",
        lambda message, history=None, **_kwargs: {
            "coach_message": "Mock coaching response.",
            "exercise": None,
            "resources": [],
            "therapists": [],
            "risk_level": "normal",
            "premium_cta": None,
            "booking_proposal": None,
            "requires_confirmation": False,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestRateLimitEnforcement:
    """10 requests allowed, 11th is rejected."""

    def test_first_ten_requests_are_allowed(self, monkeypatch, rl_db):
        """Requests 1–10 from the same session must all return 200."""
        _monkeypatch_run_agent(monkeypatch)
        client = TestClient(app)
        # Use a fixed cookie so all requests share the same rate-limit bucket
        client.cookies.set(settings.session_cookie_name, "test-session-allow-10")

        for i in range(1, 11):
            status = _make_chat_request(client)
            assert status == 200, (
                f"Request {i} should be allowed (got {status}). "
                "Rate limiter should allow the first 10 requests."
            )

    def test_eleventh_request_returns_429(self, monkeypatch, rl_db):
        """The 11th request within the window must return 429."""
        _monkeypatch_run_agent(monkeypatch)
        client = TestClient(app)
        client.cookies.set(settings.session_cookie_name, "test-session-429")

        # Exhaust the limit
        for _ in range(settings.rate_limit_chat_requests):
            _make_chat_request(client)

        # 11th request must be rejected
        status = _make_chat_request(client)
        assert status == 429, (
            f"Expected 429 on request {settings.rate_limit_chat_requests + 1}, got {status}."
        )

    def test_429_response_has_friendly_message(self, monkeypatch, rl_db):
        """The 429 response body must contain a human-readable message."""
        _monkeypatch_run_agent(monkeypatch)
        client = TestClient(app)
        client.cookies.set(settings.session_cookie_name, "test-session-msg")

        for _ in range(settings.rate_limit_chat_requests):
            _make_chat_request(client)

        response = client.post("/chat", json={"message": "one more"})
        assert response.status_code == 429
        detail = response.json().get("detail", "")
        assert "too many" in detail.lower() or "wait" in detail.lower(), (
            f"Expected friendly rate-limit message, got: {detail!r}"
        )


class TestRateLimitIsolation:
    """Different session IDs must have completely separate limits."""

    def test_different_sessions_have_separate_limits(self, monkeypatch, rl_db):
        """
        Session A exhausts its limit.
        Session B should still be allowed.
        """
        _monkeypatch_run_agent(monkeypatch)
        client = TestClient(app)

        # Exhaust session A
        client_a = TestClient(app)
        client_a.cookies.set(settings.session_cookie_name, "session-A-isolation")
        for _ in range(settings.rate_limit_chat_requests):
            _make_chat_request(client_a)

        # Session A should now be rate limited
        assert _make_chat_request(client_a) == 429

        # Session B (different cookie) should still be allowed
        client_b = TestClient(app)
        client_b.cookies.set(settings.session_cookie_name, "session-B-isolation")
        assert _make_chat_request(client_b) == 200, (
            "Session B should not be affected by Session A's rate limit."
        )

    def test_each_session_gets_full_quota(self, monkeypatch, rl_db):
        """Each session independently gets the full 10-request quota."""
        _monkeypatch_run_agent(monkeypatch)

        for session_id in ["quota-session-1", "quota-session-2", "quota-session-3"]:
            client = TestClient(app)
            client.cookies.set(settings.session_cookie_name, session_id)

            for i in range(1, settings.rate_limit_chat_requests + 1):
                status = _make_chat_request(client)
                assert status == 200, (
                    f"Session {session_id!r}: request {i} should be allowed, got {status}."
                )

            # 11th should be rejected for every session
            assert _make_chat_request(client) == 429, (
                f"Session {session_id!r}: 11th request should be rejected."
            )


class TestRateLimiterUnit:
    """Direct unit tests on the RateLimiter class itself."""

    def test_rate_limiter_allows_up_to_limit(self):
        """check() should succeed for exactly max_requests calls."""
        from app.security.rate_limiter import RateLimiter
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            rl.check("unit-key")  # must not raise

    def test_rate_limiter_raises_on_exceed(self):
        """check() should raise RateLimitExceeded on the (max+1)th call."""
        from app.security.rate_limiter import RateLimiter, RateLimitExceeded
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.check("exceed-key")
        with pytest.raises(RateLimitExceeded):
            rl.check("exceed-key")

    def test_rate_limiter_remaining_decrements(self):
        """remaining() should count down correctly."""
        from app.security.rate_limiter import RateLimiter
        rl = RateLimiter(max_requests=5, window_seconds=60)
        assert rl.remaining("rem-key") == 5
        rl.check("rem-key")
        assert rl.remaining("rem-key") == 4
        rl.check("rem-key")
        assert rl.remaining("rem-key") == 3

    def test_rate_limiter_reset_clears_state(self):
        """reset() should allow the key to start fresh."""
        from app.security.rate_limiter import RateLimiter, RateLimitExceeded
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.check("reset-key")
        rl.check("reset-key")
        with pytest.raises(RateLimitExceeded):
            rl.check("reset-key")
        rl.reset("reset-key")
        rl.check("reset-key")  # must not raise after reset

    def test_different_keys_are_independent(self):
        """Two different keys must not share quota."""
        from app.security.rate_limiter import RateLimiter, RateLimitExceeded
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.check("key-x")
        with pytest.raises(RateLimitExceeded):
            rl.check("key-x")
        # key-y is unaffected
        rl.check("key-y")  # must not raise
