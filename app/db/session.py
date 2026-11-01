from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


@lru_cache
def get_engine() -> Engine:
    url = settings.database_url
    if url.startswith("sqlite"):
        # In-memory SQLite (tests) needs one shared connection across threads.
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    # UTC session so date() bucketing of timestamps matches the UTC day used everywhere else.
    return create_engine(url, pool_pre_ping=True, connect_args={"options": "-c timezone=utc"})


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with get_sessionmaker()() as db:
        yield db
