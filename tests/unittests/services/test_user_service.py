import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.user import UserRole
from app.services.notification_service import NotificationService
from app.services.user_service import UserService
from app.schemas.user import UserCreate, UserUpdate
from app.services.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
    UserForbiddenError,
    CurrentPasswordRequiredError,
    InvalidCredentialsError,
)

# TODO: create a _make_service method that will handle the instantiation of user service
# instead of calling UserService() every test method.

# TODO: refactor this test file to be more organized and readable.


def _user_with_password(id, password="oldpassword", role=UserRole.USER):
    """A current_user stand-in with a real password_hash, for tests that
    exercise self-service password re-authentication."""
    return SimpleNamespace(id=id, role=role, password_hash=hash_password(password))


class SpyNotificationService(NotificationService):
    def __init__(self):
        self.calls = []

    def notify_password_changed(self, user):
        self.calls.append(user)


class PasswordUpdateRepo:
    """Fake repo for update_user password-change tests."""

    def __init__(self, target_user):
        self._target = target_user

    async def get_by_email(self, db, email):
        return None

    async def get_by_username(self, db, username):
        return None

    async def update(self, db, id, payload):
        return self._target


@pytest.mark.asyncio
async def test_self_password_change_without_current_password_raises(mock_db) -> None:
    me = _user_with_password("me")
    svc = UserService(user_repo=PasswordUpdateRepo(SimpleNamespace(id="me")))

    payload = UserUpdate(password="newpassword")

    with pytest.raises(CurrentPasswordRequiredError):
        await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)


@pytest.mark.asyncio
async def test_self_password_change_with_wrong_current_password_raises(mock_db) -> None:
    me = _user_with_password("me", password="oldpassword")
    svc = UserService(user_repo=PasswordUpdateRepo(SimpleNamespace(id="me")))

    payload = UserUpdate(password="newpassword", current_password="totally-wrong")

    with pytest.raises(InvalidCredentialsError):
        await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)


@pytest.mark.asyncio
async def test_self_password_change_with_correct_current_password_succeeds(mock_db) -> None:
    target = SimpleNamespace(id="me")
    me = _user_with_password("me", password="oldpassword")
    spy = SpyNotificationService()
    svc = UserService(user_repo=PasswordUpdateRepo(target), notification_service=spy)

    payload = UserUpdate(password="newpassword", current_password="oldpassword")
    result = await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)

    assert result is target
    assert spy.calls == [target]


@pytest.mark.asyncio
async def test_admin_resetting_another_users_password_does_not_require_current_password(mock_db) -> None:
    target = SimpleNamespace(id="other")
    admin = _admin(id="admin")
    spy = SpyNotificationService()
    svc = UserService(user_repo=PasswordUpdateRepo(target), notification_service=spy)

    payload = UserUpdate(password="newpassword")  # no current_password
    result = await svc.update_user(db=mock_db, id="other", payload=payload, current_user=admin)

    assert result is target
    assert spy.calls == [target]


@pytest.mark.asyncio
async def test_non_password_update_does_not_notify(mock_db) -> None:
    target = SimpleNamespace(id="me")
    me = _user_with_password("me")
    spy = SpyNotificationService()
    svc = UserService(user_repo=PasswordUpdateRepo(target), notification_service=spy)

    payload = UserUpdate(full_name="New Name")
    await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)

    assert spy.calls == []


def _admin(id="admin"):
    return SimpleNamespace(id=id, role=UserRole.ADMIN)


def _regular(id="me"):
    return SimpleNamespace(id=id, role=UserRole.USER)


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

    async def worker():
        try:
            return await svc.create_user(db=None, payload=payload)
        except Exception as e:
            return e

    results = await asyncio.gather(
        worker(),
        worker(),
    )

    email_errors = [r for r in results if isinstance(r, EmailAlreadyExistsError)]

    assert len(email_errors) == 1


class BaseRepo:
    async def get_by_id(self, db, id) -> Any:
        return None

    async def get_by_email(self, db, email) -> Any:
        return None

    async def get_all(self, db, skip=0, limit=100):
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
        await svc.update_user(db=mock_db, id="id", payload=UserUpdate(username="collision"), current_user=_admin())


@pytest.mark.asyncio
async def test_get_user_not_found_raises(mock_db):
    svc = UserService(user_repo=BaseRepo())

    with pytest.raises(UserNotFoundError):
        await svc.get_user(db=mock_db, id="nope", current_user=_admin())


@pytest.mark.asyncio
async def test_update_user_precheck_email_collision(mock_db):
    class Repo(BaseRepo):
        async def get_by_email(self, db, email):
            return SimpleNamespace(id="other")

    svc = UserService(user_repo=Repo())

    with pytest.raises(EmailAlreadyExistsError):
        await svc.update_user(db=mock_db, id="me", payload=UserUpdate(email="e@x.com"), current_user=_regular("me"))


@pytest.mark.asyncio
async def test_update_user_precheck_username_collision(mock_db):
    class Repo(BaseRepo):
        async def get_by_username(self, db, username):
            return SimpleNamespace(id="other")

    svc = UserService(user_repo=Repo())

    with pytest.raises(UsernameAlreadyExistsError):
        await svc.update_user(db=mock_db, id="me", payload=UserUpdate(username="u"), current_user=_regular("me"))


@pytest.mark.asyncio
async def test_update_user_not_found_raises(mock_db):
    svc = UserService(user_repo=BaseRepo())

    with pytest.raises(UserNotFoundError):
        await svc.update_user(db=mock_db, id="me", payload=UserUpdate(), current_user=_regular("me"))


@pytest.mark.asyncio
async def test_delete_user_not_found_raises(mock_db):
    svc = UserService(user_repo=BaseRepo())

    with pytest.raises(UserNotFoundError):
        await svc.delete_user(db=mock_db, id="me", current_user=_admin())


# ─── list_users ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListUsers:
    async def test_admin_can_list(self, mock_db):
        class Repo(BaseRepo):
            async def get_all(self, db, skip=0, limit=100):
                return ["u1", "u2"]

        svc = UserService(user_repo=Repo())
        result = await svc.list_users(db=mock_db, current_user=_admin())
        assert result == ["u1", "u2"]

    async def test_user_role_is_forbidden(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(UserForbiddenError):
            await svc.list_users(db=mock_db, current_user=_regular())

    async def test_current_user_is_required(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(TypeError):
            await svc.list_users(db=mock_db)


# ─── get_user authorization ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetUserAuthorization:
    async def test_self_can_get_own_profile(self, mock_db):
        class Repo(BaseRepo):
            async def get_by_id(self, db, id):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        result = await svc.get_user(db=mock_db, id="me", current_user=_regular("me"))
        assert result.id == "me"

    async def test_admin_can_get_any_profile(self, mock_db):
        class Repo(BaseRepo):
            async def get_by_id(self, db, id):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        result = await svc.get_user(db=mock_db, id="someone-else", current_user=_admin())
        assert result.id == "someone-else"

    async def test_forbidden_for_another_users_profile(self, mock_db):
        class Repo(BaseRepo):
            async def get_by_id(self, db, id):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        with pytest.raises(UserForbiddenError):
            await svc.get_user(db=mock_db, id="someone-else", current_user=_regular("me"))

    async def test_current_user_is_required(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(TypeError):
            await svc.get_user(db=mock_db, id="me")


# ─── update_user authorization ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateUserAuthorization:
    async def test_self_can_update_own_profile(self, mock_db):
        class Repo(BaseRepo):
            async def update(self, db, id, payload):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        result = await svc.update_user(
            db=mock_db, id="me", payload=UserUpdate(full_name="New Name"), current_user=_regular("me")
        )
        assert result.id == "me"

    async def test_admin_can_update_any_profile(self, mock_db):
        class Repo(BaseRepo):
            async def update(self, db, id, payload):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        result = await svc.update_user(
            db=mock_db, id="someone-else", payload=UserUpdate(full_name="New Name"), current_user=_admin()
        )
        assert result.id == "someone-else"

    async def test_forbidden_for_another_users_profile(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(UserForbiddenError):
            await svc.update_user(
                db=mock_db,
                id="someone-else",
                payload=UserUpdate(full_name="New Name"),
                current_user=_regular("me"),
            )

    async def test_non_admin_cannot_change_own_role(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(UserForbiddenError):
            await svc.update_user(
                db=mock_db, id="me", payload=UserUpdate(role=UserRole.ADMIN), current_user=_regular("me")
            )

    async def test_admin_can_change_a_users_role(self, mock_db):
        class Repo(BaseRepo):
            async def update(self, db, id, payload):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        result = await svc.update_user(
            db=mock_db, id="someone-else", payload=UserUpdate(role=UserRole.MANAGER), current_user=_admin()
        )
        assert result.id == "someone-else"

    async def test_current_user_is_required(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(TypeError):
            await svc.update_user(db=mock_db, id="me", payload=UserUpdate())


# ─── delete_user authorization ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteUserAuthorization:
    async def test_admin_can_delete_another_user(self, mock_db):
        class Repo(BaseRepo):
            async def delete(self, db, id):
                return SimpleNamespace(id=id)

        svc = UserService(user_repo=Repo())
        result = await svc.delete_user(db=mock_db, id="someone-else", current_user=_admin())
        assert result.id == "someone-else"
        assert mock_db.commit.called

    async def test_non_admin_is_forbidden(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(UserForbiddenError):
            await svc.delete_user(db=mock_db, id="someone-else", current_user=_regular("me"))

    async def test_admin_cannot_delete_own_account(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(UserForbiddenError):
            await svc.delete_user(db=mock_db, id="admin", current_user=_admin("admin"))

    async def test_current_user_is_required(self, mock_db):
        svc = UserService(user_repo=BaseRepo())
        with pytest.raises(TypeError):
            await svc.delete_user(db=mock_db, id="someone-else")
