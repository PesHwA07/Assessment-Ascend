"""
SQLite database engine and session management via SQLAlchemy.

Provides:
- engine:          SQLAlchemy engine bound to the SQLite file in data/
- SessionLocal:    scoped session factory for request-level transactions
- get_db():        FastAPI dependency that yields a session and auto-closes
- init_db():       creates all tables (called at app startup)
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},   # required for SQLite + FastAPI
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables defined in db_models.  Call once at startup."""
    from app.db_models import Base          # deferred import to avoid circular
    Base.metadata.create_all(bind=engine)
