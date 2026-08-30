"""
Root conftest.py for all tests (unit and integration).

Provides an in-memory SQLite database and in-memory VectorStore for all tests
so they do not require a real on-disk database or external Qdrant instance.
"""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.vector_store import VectorStore, init_vector_store
from app.models import Base

# ── In-memory async SQLite engine (shared across all tests) ───────────────────

_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def test_engine():
    """Create all tables in an in-memory SQLite DB once per test session."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(test_engine):
    """Yield a fresh async session, rolling back after each test."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def memory_vector_store() -> VectorStore:
    """Initialize an in-memory VectorStore for tests."""
    client = QdrantClient(":memory:")
    return await init_vector_store(client)


@pytest.fixture(autouse=True)
def patch_get_db(db_session, monkeypatch):
    """
    Replace the FastAPI `get_db` dependency with one that returns the
    test session.
    """

    async def _override():
        yield db_session

    import app.routers.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "get_db", _override)

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def patch_init_db(monkeypatch):
    """Prevent lifespan from calling real init_db and real Qdrant init."""
    import app.main as main_mod

    async def _noop(*args, **kwargs):
        pass

    monkeypatch.setattr(main_mod, "init_db", _noop)

    # Also prevent lifespan from creating a file-based Qdrant client
    # (which would conflict with the in-memory one from memory_vector_store)
    from app.agents import vector_store as vs_mod

    async def _noop_vs(*args, **kwargs):
        pass

    monkeypatch.setattr(vs_mod, "init_vector_store", _noop_vs)
