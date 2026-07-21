import pytest
from unittest.mock import AsyncMock

from app.db import session as session_module


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_get_db_does_not_commit_on_normal_exit(monkeypatch):
    fake_session = _FakeSession()
    monkeypatch.setattr(session_module, "AsyncSessionLocal", lambda: _FakeSessionFactory(fake_session))

    agen = session_module.get_db()
    session = await agen.__anext__()

    assert session is fake_session

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()

    fake_session.commit.assert_not_awaited()
    fake_session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception(monkeypatch):
    fake_session = _FakeSession()
    monkeypatch.setattr(session_module, "AsyncSessionLocal", lambda: _FakeSessionFactory(fake_session))

    agen = session_module.get_db()
    session = await agen.__anext__()

    assert session is fake_session

    with pytest.raises(RuntimeError):
        await agen.athrow(RuntimeError("boom"))

    fake_session.commit.assert_not_awaited()
    fake_session.rollback.assert_awaited_once()
