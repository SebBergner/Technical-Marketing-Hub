"""Database engine and session handling."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.tables import Base

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # SQLite only: the file must exist on disk before the engine connects.
    path = settings.database_url.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, echo=settings.sql_echo, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_all() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
