import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.user_service import UserService
from app.schemas.user import UserCreate, UserUpdate
from app.services.exceptions import EmailAlreadyExistsError, UsernameAlreadyExistsError, UserNotFoundError


class FakeRepoIntegrityEmail:
    async def get_by_email(self, db, email):
        return None

    async def get_by_username(self, db, username):
        return None

    async def create(self, db, payload):
        # Simulate a DB unique constraint on email
        raise IntegrityError(
            "INSERT", {}, Exception('duplicate key value violates unique constraint "users_email_key"')
        )

@pytest.mark.asyncio
async def test_create_user_translates_integrity_error_to_email_conflict(mock_db) -> None:
    repo = FakeRepoIntegrityEmail()
    svc = UserService(user_repo=repo)

    payload = UserCreate(username="u", email="e@example.com", full_name="Name", password="pw")

    with pytest.raises(EmailAlreadyExistsError):
        await svc.create_user(db=mock_db, payload=payload)


class RaceRepo:
    """Simulates a race where the second create hits a unique constraint."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._calls = 0

    async def get_by_email(self, db, email):
        return None

    async def get_by_username(self, db, username):
        return None

    async def create(self, db, payload):
        async with self._lock:
            self._calls += 1
            if self._calls == 1:
                # First caller 'succeeds'
                return SimpleNamespace(id="first")

        # Second caller fails with DB IntegrityError
        raise IntegrityError(
            "INSERT", {}, Exception('duplicate key value violates unique constraint "users_email_key"')
        )

@pytest.mark.asyncio
async def test_concurrent_creates_one_fails_with_email_conflict() -> None:
    repo = RaceRepo()
    svc = UserService(user_repo=repo)
    payload = UserCreate(username="u", email="e@example.com", full_name="Name", password="pw")

    results = [None, None]
    errors = [None, None]

    async def worker():
        try:
            return await svc.create_user(db=None, payload=payload)
        except Exception as e:
            return e

    results = await asyncio.gather(
        worker(),
        worker(),
    )
    
    email_errors = [
        r for r in results
        if isinstance(r, EmailAlreadyExistsError)
    ]
    
    assert len(email_errors) == 1


class BaseRepo:
    async def get_by_id(self, db, id) -> Any:
        return None
    async def get_by_email(self, db, email) -> Any:
        return None
    async def get_by_username(self, db, username) -> Any:
        return None
    async def update(self, db, id, payload) -> Any:
        return None
    async def delete(self, db, id) -> Any:
        return None
    

@pytest.mark.asyncio
async def test_update_user_translates_integrity_error(mock_db) -> None:
    class UpdateRepo(BaseRepo):
        async def update(self, db, id, payload):
            raise IntegrityError(
                "UPDATE", {}, Exception('duplicate key value violates unique constraint "users_username_key"')
            )

    svc = UserService(user_repo=UpdateRepo())

    with pytest.raises(UsernameAlreadyExistsError):
        await svc.update_user(db=mock_db, id="id", payload=UserUpdate(username="collision"))

@pytest.mark.asyncio
async def test_get_user_not_found_raises(mock_db):

    svc = UserService(user_repo=BaseRepo())

    with pytest.raises(UserNotFoundError):
        await svc.get_user(db=mock_db, id="nope")

@pytest.mark.asyncio
async def test_update_user_precheck_email_collision(mock_db):
    class Repo(BaseRepo):
        async def get_by_email(self, db, email):
            return SimpleNamespace(id="other")


    svc = UserService(user_repo=Repo())

    with pytest.raises(EmailAlreadyExistsError):
        await svc.update_user(db=mock_db, id="me", payload=UserUpdate(email="e@x.com"))

@pytest.mark.asyncio
async def test_update_user_precheck_username_collision(mock_db):
    class Repo(BaseRepo):

        async def get_by_username(self, db, username):
            return SimpleNamespace(id="other")

    svc = UserService(user_repo=Repo())

    with pytest.raises(UsernameAlreadyExistsError):
        await svc.update_user(db=mock_db, id="me", payload=UserUpdate(username="u"))

@pytest.mark.asyncio
async def test_update_user_not_found_raises(mock_db):

    svc = UserService(user_repo=BaseRepo())

    with pytest.raises(UserNotFoundError):
        await svc.update_user(db=mock_db, id="me", payload=UserUpdate())

@pytest.mark.asyncio
async def test_delete_user_not_found_raises(mock_db):

    svc = UserService(user_repo=BaseRepo())

    with pytest.raises(UserNotFoundError):
        await svc.delete_user(db=mock_db, id="me")
