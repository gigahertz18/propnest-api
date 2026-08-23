from unittest.mock import MagicMock

from app.db import provisioning


class _FakeConnection:
    def __init__(self, fetchone_result):
        self._fetchone_result = fetchone_result
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        result = MagicMock()
        result.fetchone.return_value = self._fetchone_result
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection):
        self._connection = connection
        self.disposed = False

    def connect(self):
        return self._connection

    def dispose(self):
        self.disposed = True


def test_ensure_database_exists_creates_db_when_missing(monkeypatch):
    connection = _FakeConnection(fetchone_result=None)  # SELECT 1 finds nothing
    engine = _FakeEngine(connection)
    monkeypatch.setattr(provisioning, "create_engine", lambda *a, **k: engine)

    provisioning.ensure_database_exists()

    create_calls = [sql for sql, _ in connection.executed if "CREATE DATABASE" in sql]
    assert len(create_calls) == 1
    assert engine.disposed is True


def test_ensure_database_exists_skips_creation_when_already_present(monkeypatch):
    connection = _FakeConnection(fetchone_result=(1,))  # SELECT 1 finds a row
    engine = _FakeEngine(connection)
    monkeypatch.setattr(provisioning, "create_engine", lambda *a, **k: engine)

    provisioning.ensure_database_exists()

    create_calls = [sql for sql, _ in connection.executed if "CREATE DATABASE" in sql]
    assert create_calls == []
    assert engine.disposed is True


def test_ensure_database_exists_disposes_engine_even_on_error(monkeypatch):
    class _ExplodingConnection(_FakeConnection):
        def execute(self, stmt, params=None):
            raise RuntimeError("connection refused")

    engine = _FakeEngine(_ExplodingConnection(fetchone_result=None))
    monkeypatch.setattr(provisioning, "create_engine", lambda *a, **k: engine)

    try:
        provisioning.ensure_database_exists()
    except RuntimeError:
        pass

    assert engine.disposed is True


def test_run_migrations_upgrades_to_head(monkeypatch):
    upgrade_calls = []
    monkeypatch.setattr(
        provisioning.command,
        "upgrade",
        lambda cfg, revision: upgrade_calls.append((cfg, revision)),
    )

    provisioning.run_migrations()

    assert len(upgrade_calls) == 1
    _, revision = upgrade_calls[0]
    assert revision == "head"
