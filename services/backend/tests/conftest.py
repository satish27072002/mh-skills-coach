import os

import pytest

from app import config, db

TEST_DATABASE_URL = "sqlite+pysqlite:///./test.db"


@pytest.fixture(autouse=True, scope="session")
def _configure_test_db():
    if os.path.exists("./test.db"):
        os.remove("./test.db")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    config.settings.database_url = TEST_DATABASE_URL
    db.reset_engine(TEST_DATABASE_URL)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the rate limiter before every test so tests don't share state."""
    from app.main import _rate_limiter
    _rate_limiter._store.clear()
    yield
    _rate_limiter._store.clear()


@pytest.fixture(autouse=True)
def _reset_conversation_store():
    """Reset conversation history before every test."""
    from app.main import _conversation_store
    _conversation_store.clear()
    yield
    _conversation_store.clear()
