import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.identity.models.user import UserRole
from app.core.services.notification_service import NotificationService
from app.identity.services.user_service import UserService
from app.identity.schemas.user import UserCreate, UserUpdate
from app.core.services.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
    UserForbiddenError,
    CurrentPasswordRequiredError,
    InvalidCredentialsError,
)
from tests.mock_repos import MockCRUDRepo

# ─── current_user stand-ins ─────────────────────────────────────────────────


def _admin(id="admin"):
    return SimpleNamespace(id=id, role=UserRole.ADMIN)


def _regular(id="me"):
    return SimpleNamespace(id=id, role=UserRole.USER)


def _user_with_password(id, password="oldpassword", role=UserRole.USER):
    """A current_user stand-in with a real password_hash, for tests that
    exercise self-service password re-authentication."""
    return SimpleNamespace(id=id, role=role, password_hash=hash_password(password))


# ─── fake repo ───────────────────────────────────────────────────────────────


class MockUserRepo(MockCRUDRepo):
    """Adds get_by_email/get_by_username on top of MockCRUDRepo, mirroring
    UserRepository — the same pattern as MockTenantRepo.get_by_user_id."""

    async def get_by_email(self, db, email):
        results = await self._filter_by(email=email)
        return results[0] if results else None

    async def get_by_username(self, db, username):
        results = await self._filter_by(username=username)
        return results[0] if results else None


class SpyNotificationService(NotificationService):
    def __init__(self):
        self.calls = []

    def notify_password_changed(self, user):
        self.calls.append(user)


# ─── service factory ─────────────────────────────────────────────────────────


def _make_service(users=None, notification_service=None) -> UserService:
    if users is None:
        user_repo = MockUserRepo({})
    elif isinstance(users, dict):
        user_repo = MockUserRepo(users)
    else:
        user_repo = users
    return UserService(user_repo=user_repo, notification_service=notification_service)


# ─── create_user ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateUser:
    async def test_translates_integrity_error_to_email_conflict(self, mock_db) -> None:
        class FailingCreateRepo(MockUserRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT", {}, Exception('duplicate key value violates unique constraint "users_email_key"')
                )

        svc = _make_service(users=FailingCreateRepo())
        payload = UserCreate(username="u", email="e@example.com", full_name="Name", password="pw")

        with pytest.raises(EmailAlreadyExistsError):
            await svc.create_user(db=mock_db, payload=payload, current_user=_admin())

    async def test_concurrent_creates_one_fails_with_email_conflict(self) -> None:
        """Simulates a race where the second create hits a unique constraint
        after both callers pass the pre-check."""

        class RaceRepo(MockUserRepo):
            def __init__(self):
                super().__init__()
                self._lock = asyncio.Lock()
                self._calls = 0

            async def create(self, db, payload):
                async with self._lock:
                    self._calls += 1
                    if self._calls == 1:
                        return SimpleNamespace(id="first")  # first caller 'succeeds'
                raise IntegrityError(
                    "INSERT", {}, Exception('duplicate key value violates unique constraint "users_email_key"')
                )

        svc = _make_service(users=RaceRepo())
        payload = UserCreate(username="u", email="e@example.com", full_name="Name", password="pw")

        async def worker():
            try:
                return await svc.create_user(db=None, payload=payload, current_user=_admin())
            except Exception as e:
                return e

        results = await asyncio.gather(worker(), worker())

        email_errors = [r for r in results if isinstance(r, EmailAlreadyExistsError)]
        assert len(email_errors) == 1


# ─── get_user ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetUser:
    async def test_self_can_get_own_profile(self, mock_db):
        svc = _make_service(users={"me": SimpleNamespace(id="me")})
        result = await svc.get_user(db=mock_db, id="me", current_user=_regular("me"))
        assert result.id == "me"

    async def test_admin_can_get_any_profile(self, mock_db):
        svc = _make_service(users={"someone-else": SimpleNamespace(id="someone-else")})
        result = await svc.get_user(db=mock_db, id="someone-else", current_user=_admin())
        assert result.id == "someone-else"

    async def test_forbidden_for_another_users_profile(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserForbiddenError):
            await svc.get_user(db=mock_db, id="someone-else", current_user=_regular("me"))

    async def test_not_found_raises(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserNotFoundError):
            await svc.get_user(db=mock_db, id="nope", current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        svc = _make_service()
        with pytest.raises(TypeError):
            await svc.get_user(db=mock_db, id="me")


# ─── list_users ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListUsers:
    async def test_admin_can_list(self, mock_db):
        svc = _make_service(users={"u1": SimpleNamespace(id="u1"), "u2": SimpleNamespace(id="u2")})
        result = await svc.list_users(db=mock_db, current_user=_admin())
        assert [u.id for u in result] == ["u1", "u2"]

    async def test_user_role_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserForbiddenError):
            await svc.list_users(db=mock_db, current_user=_regular())

    async def test_current_user_is_required(self, mock_db):
        svc = _make_service()
        with pytest.raises(TypeError):
            await svc.list_users(db=mock_db)


# ─── update_user: authorization ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateUserAuthorization:
    async def test_self_can_update_own_profile(self, mock_db):
        svc = _make_service(users={"me": SimpleNamespace(id="me", full_name="Old Name")})
        result = await svc.update_user(
            db=mock_db, id="me", payload=UserUpdate(full_name="New Name"), current_user=_regular("me")
        )
        assert result.id == "me"
        assert result.full_name == "New Name"

    async def test_admin_can_update_any_profile(self, mock_db):
        svc = _make_service(users={"someone-else": SimpleNamespace(id="someone-else", full_name="Old Name")})
        result = await svc.update_user(
            db=mock_db, id="someone-else", payload=UserUpdate(full_name="New Name"), current_user=_admin()
        )
        assert result.id == "someone-else"

    async def test_forbidden_for_another_users_profile(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserForbiddenError):
            await svc.update_user(
                db=mock_db,
                id="someone-else",
                payload=UserUpdate(full_name="New Name"),
                current_user=_regular("me"),
            )

    async def test_non_admin_cannot_change_own_role(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserForbiddenError):
            await svc.update_user(
                db=mock_db, id="me", payload=UserUpdate(role=UserRole.ADMIN), current_user=_regular("me")
            )

    async def test_admin_can_change_a_users_role(self, mock_db):
        svc = _make_service(users={"someone-else": SimpleNamespace(id="someone-else", role=UserRole.USER)})
        result = await svc.update_user(
            db=mock_db, id="someone-else", payload=UserUpdate(role=UserRole.MANAGER), current_user=_admin()
        )
        assert result.id == "someone-else"

    async def test_current_user_is_required(self, mock_db):
        svc = _make_service()
        with pytest.raises(TypeError):
            await svc.update_user(db=mock_db, id="me", payload=UserUpdate())


# ─── update_user: field validation / conflicts ──────────────────────────────


@pytest.mark.asyncio
class TestUpdateUserValidation:
    async def test_translates_integrity_error_on_username_collision(self, mock_db) -> None:
        class FailingUpdateRepo(MockUserRepo):
            async def update(self, db, id, payload):
                raise IntegrityError(
                    "UPDATE", {}, Exception('duplicate key value violates unique constraint "users_username_key"')
                )

        svc = _make_service(users=FailingUpdateRepo())
        with pytest.raises(UsernameAlreadyExistsError):
            await svc.update_user(db=mock_db, id="id", payload=UserUpdate(username="collision"), current_user=_admin())

    async def test_precheck_email_collision(self, mock_db):
        svc = _make_service(users={"other": SimpleNamespace(id="other", email="e@x.com", username="other")})
        with pytest.raises(EmailAlreadyExistsError):
            await svc.update_user(db=mock_db, id="me", payload=UserUpdate(email="e@x.com"), current_user=_regular("me"))

    async def test_precheck_username_collision(self, mock_db):
        svc = _make_service(users={"other": SimpleNamespace(id="other", email="other@x.com", username="collision")})
        with pytest.raises(UsernameAlreadyExistsError):
            await svc.update_user(
                db=mock_db, id="me", payload=UserUpdate(username="collision"), current_user=_regular("me")
            )

    async def test_returns_not_found_when_missing(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserNotFoundError):
            await svc.update_user(db=mock_db, id="me", payload=UserUpdate(), current_user=_regular("me"))


# ─── update_user: self-service password re-authentication ──────────────────


@pytest.mark.asyncio
class TestUpdateUserPasswordChange:
    async def test_self_change_without_current_password_raises(self, mock_db) -> None:
        me = _user_with_password("me")
        svc = _make_service()  # never reaches the repo — raises before any lookup

        payload = UserUpdate(password="newpassword")

        with pytest.raises(CurrentPasswordRequiredError):
            await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)

    async def test_self_change_with_wrong_current_password_raises(self, mock_db) -> None:
        me = _user_with_password("me", password="oldpassword")
        svc = _make_service()

        payload = UserUpdate(password="newpassword", current_password="totally-wrong")

        with pytest.raises(InvalidCredentialsError):
            await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)

    async def test_self_change_with_correct_current_password_succeeds(self, mock_db) -> None:
        target = SimpleNamespace(id="me")
        me = _user_with_password("me", password="oldpassword")
        spy = SpyNotificationService()
        svc = _make_service(users={"me": target}, notification_service=spy)

        payload = UserUpdate(password="newpassword", current_password="oldpassword")
        result = await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)

        assert result is target
        assert spy.calls == [target]

    async def test_admin_resetting_another_users_password_does_not_require_current_password(self, mock_db) -> None:
        target = SimpleNamespace(id="other")
        admin = _admin(id="admin")
        spy = SpyNotificationService()
        svc = _make_service(users={"other": target}, notification_service=spy)

        payload = UserUpdate(password="newpassword")  # no current_password
        result = await svc.update_user(db=mock_db, id="other", payload=payload, current_user=admin)

        assert result is target
        assert spy.calls == [target]

    async def test_non_password_update_does_not_notify(self, mock_db) -> None:
        target = SimpleNamespace(id="me")
        me = _user_with_password("me")
        spy = SpyNotificationService()
        svc = _make_service(users={"me": target}, notification_service=spy)

        payload = UserUpdate(full_name="New Name")
        await svc.update_user(db=mock_db, id="me", payload=payload, current_user=me)

        assert spy.calls == []


# ─── delete_user ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteUser:
    async def test_admin_can_delete_another_user(self, mock_db):
        svc = _make_service(users={"someone-else": SimpleNamespace(id="someone-else")})
        result = await svc.delete_user(db=mock_db, id="someone-else", current_user=_admin())
        assert result.id == "someone-else"
        assert mock_db.commit.called

    async def test_non_admin_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserForbiddenError):
            await svc.delete_user(db=mock_db, id="someone-else", current_user=_regular("me"))

    async def test_admin_cannot_delete_own_account(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserForbiddenError):
            await svc.delete_user(db=mock_db, id="admin", current_user=_admin("admin"))

    async def test_not_found_raises(self, mock_db):
        svc = _make_service()
        with pytest.raises(UserNotFoundError):
            await svc.delete_user(db=mock_db, id="me", current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        svc = _make_service()
        with pytest.raises(TypeError):
            await svc.delete_user(db=mock_db, id="someone-else")
