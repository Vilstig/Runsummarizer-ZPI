from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import POSTGRES_DSN

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Process-wide async engine, and the connection pool behind it."""
    global _engine
    if _engine is None:
        if not POSTGRES_DSN:
            raise RuntimeError("POSTGRES_DSN is not configured")
        _engine = create_async_engine(POSTGRES_DSN)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Factory for sessions on the process-wide engine."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def open_session() -> AsyncGenerator[AsyncSession]:
    """A session on the process-wide engine, committed when the block exits cleanly.

    An exception skips the commit, and closing the session rolls the transaction back.
    """
    async with get_sessionmaker()() as session:
        yield session
        await session.commit()


async def dispose_engine() -> None:
    """Close the pooled Postgres connections."""
    global _engine, _sessionmaker
    _sessionmaker = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None
