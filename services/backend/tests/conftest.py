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
