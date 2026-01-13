from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    from . import models

    Base.metadata.create_all(bind=engine)


def reset_engine(database_url: str | None = None) -> None:
    global engine, SessionLocal
    engine.dispose()
    engine = _make_engine(database_url or settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
