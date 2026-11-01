"""Session factory, FastAPI dependency and transactional helper."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker

from app.database.connection import get_engine

_factory: sessionmaker[Session] | None = None
_factory_engine = None


def session_factory() -> sessionmaker[Session]:
    global _factory, _factory_engine
    engine = get_engine()
    if _factory is None or _factory_engine is not engine:
        _factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        _factory_engine = engine
    return _factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background work: commit on success, rollback on error."""
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
