"""
tests/integration/test_seed_admin.py

Smoke test for scripts/seed_admin.py.

This directly exercises `scripts.seed_admin.seed()` against the test
database to catch import-time and sync/async API regressions early —
the kind of bug that a lint/format/unit-test-only CI pipeline won't
surface (the previous version imported a `SessionLocal` that didn't
exist in app/db/session.py, and used the SQLAlchemy 1.x sync ORM API
against what is actually an async session).

Deliberately minimal: this only imports what scripts/seed_admin.py
itself already imports (AsyncSessionLocal, the User model). It does
not go through UserService, UserRepository, or any route/client
fixture — seed_admin.py is a standalone script by design and this test
respects that.
"""

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.user import User
from scripts.seed_admin import seed

TEST_USERNAME = "seed_smoke_test_admin"
TEST_EMAIL = "seed_smoke_test_admin@propnest.com"
TEST_PASSWORD = "seed-smoke-test-password"


@pytest.mark.asyncio
async def test_seed_creates_admin_user(monkeypatch):
    monkeypatch.setenv("SEED_USERNAME", TEST_USERNAME)
    monkeypatch.setenv("SEED_EMAIL", TEST_EMAIL)
    monkeypatch.setenv("SEED_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("SEED_FULL_NAME", "Seed Smoke Test")

    try:
        await seed()

        async with AsyncSessionLocal() as db:
            created = (await db.execute(select(User).where(User.username == TEST_USERNAME))).scalar_one_or_none()

        assert created is not None
        assert created.email == TEST_EMAIL
        assert created.role.value == "admin"
        assert created.is_active is True
    finally:
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(select(User).where(User.username == TEST_USERNAME))).scalar_one_or_none()
            if existing:
                await db.delete(existing)
                await db.commit()


@pytest.mark.asyncio
async def test_seed_skips_when_username_already_exists(monkeypatch):
    monkeypatch.setenv("SEED_USERNAME", TEST_USERNAME)
    monkeypatch.setenv("SEED_EMAIL", TEST_EMAIL)
    monkeypatch.setenv("SEED_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("SEED_FULL_NAME", "Seed Smoke Test")

    try:
        await seed()  # first run creates the user
        await seed()  # second run should skip — not raise, not duplicate

        async with AsyncSessionLocal() as db:
            matches = (await db.execute(select(User).where(User.username == TEST_USERNAME))).scalars().all()

        assert len(matches) == 1
    finally:
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(select(User).where(User.username == TEST_USERNAME))).scalar_one_or_none()
            if existing:
                await db.delete(existing)
                await db.commit()
