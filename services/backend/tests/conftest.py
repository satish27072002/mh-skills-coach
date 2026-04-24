import os

import pytest

from app import config, db
from app.runtime_requirements import ensure_backend_requirements

TEST_DATABASE_URL = "sqlite+pysqlite:///./test.db"

ensure_backend_requirements(install_missing=True)


@pytest.fixture(autouse=True, scope="session")
def _configure_test_db():
    original_reset_engine = db.reset_engine

    def reset_engine_and_clear(database_url: str | None = None) -> None:
        original_reset_engine(database_url)
        db.init_db()
        from app.agent_graph import _GRAPH_CHECKPOINTER
        from app.main import _guest_prompt_store, _rate_limiter

        _GRAPH_CHECKPOINTER.clear_all()
        _guest_prompt_store.clear_all()
        _rate_limiter.clear_all()

    if os.path.exists("./test.db"):
        os.remove("./test.db")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    config.settings.database_url = TEST_DATABASE_URL
    db.reset_engine = reset_engine_and_clear
    db.reset_engine(TEST_DATABASE_URL)
    yield
    db.reset_engine = original_reset_engine


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.main import _rate_limiter
    _rate_limiter.clear_all()
    yield
    _rate_limiter.clear_all()


@pytest.fixture(autouse=True)
def _reset_graph_checkpointer():
    from app.agent_graph import _GRAPH_CHECKPOINTER

    _GRAPH_CHECKPOINTER.clear_all()
    yield
    _GRAPH_CHECKPOINTER.clear_all()


@pytest.fixture(autouse=True)
def _reset_guest_prompt_counts():
    from app.main import _guest_prompt_store
    _guest_prompt_store.clear_all()
    yield
    _guest_prompt_store.clear_all()


@pytest.fixture(autouse=True)
def _reset_settings_defaults():
    original_dev_mode = config.settings.dev_mode
    config.settings.dev_mode = False
    yield
    config.settings.dev_mode = original_dev_mode
