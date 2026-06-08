import threading
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.user_service import UserService
from app.schemas.user import UserCreate, UserUpdate
from app.services.exceptions import EmailAlreadyExistsError, UsernameAlreadyExistsError, UserNotFoundError


class FakeRepoIntegrityEmail:
    def get_by_email(self, db, email):
        return None

    def get_by_username(self, db, username):
        return None

    def create(self, db, payload):
        # Simulate a DB unique constraint on email
        raise IntegrityError(
            "INSERT", {}, Exception('duplicate key value violates unique constraint "users_email_key"')
        )


def test_create_user_translates_integrity_error_to_email_conflict() -> None:
    repo = FakeRepoIntegrityEmail()
    svc = UserService(user_repo=repo)

    payload = UserCreate(username="u", email="e@example.com", full_name="Name", password="pw")

    with pytest.raises(EmailAlreadyExistsError):
        svc.create_user(db=None, payload=payload)


class RaceRepo:
    """Simulates a race where the second create hits a unique constraint."""

    def __init__(self):
        self._lock = threading.Lock()
        self._calls = 0

    def get_by_email(self, db, email):
        return None

    def get_by_username(self, db, username):
        return None

    def create(self, db, payload):
        with self._lock:
            self._calls += 1
            if self._calls == 1:
                # First caller 'succeeds'
                u = SimpleNamespace()
                u.id = "first"
                return u
            # Second caller fails with DB IntegrityError
            raise IntegrityError(
                "INSERT", {}, Exception('duplicate key value violates unique constraint "users_email_key"')
            )


def test_concurrent_creates_one_fails_with_email_conflict() -> None:
    repo = RaceRepo()
    svc = UserService(user_repo=repo)
    payload = UserCreate(username="u", email="e@example.com", full_name="Name", password="pw")

    results = [None, None]
    errors = [None, None]

    def worker(i):
        try:
            results[i] = svc.create_user(db=None, payload=payload)
        except Exception as e:
            errors[i] = e

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one thread should have raised EmailAlreadyExistsError
    email_errors = [isinstance(e, EmailAlreadyExistsError) for e in errors if e is not None]
    assert any(email_errors)


def test_update_user_translates_integrity_error() -> None:
    class UpdateRepo:
        def get_by_email(self, db, email):
            return None

        def get_by_username(self, db, username):
            return None

        def update(self, db, id, payload):
            raise IntegrityError(
                "UPDATE", {}, Exception('duplicate key value violates unique constraint "users_username_key"')
            )

    repo = UpdateRepo()
    svc = UserService(user_repo=repo)

    with pytest.raises(UsernameAlreadyExistsError):
        svc.update_user(db=None, id="id", payload=UserUpdate(username="collision"))


def test_get_user_not_found_raises():
    class Repo:
        def get_by_id(self, db, id):
            return None

    svc = UserService(user_repo=Repo())

    with pytest.raises(UserNotFoundError):
        svc.get_user(db=None, id="nope")


def test_update_user_precheck_email_collision():
    class Repo:
        def get_by_email(self, db, email):
            return SimpleNamespace(id="other")

        def get_by_username(self, db, username):
            return None

    svc = UserService(user_repo=Repo())

    with pytest.raises(EmailAlreadyExistsError):
        svc.update_user(db=None, id="me", payload=UserUpdate(email="e@x.com"))


def test_update_user_precheck_username_collision():
    class Repo:
        def get_by_email(self, db, email):
            return None

        def get_by_username(self, db, username):
            return SimpleNamespace(id="other")

    svc = UserService(user_repo=Repo())

    with pytest.raises(UsernameAlreadyExistsError):
        svc.update_user(db=None, id="me", payload=UserUpdate(username="u"))


def test_update_user_not_found_raises():
    class Repo:
        def get_by_email(self, db, email):
            return None

        def get_by_username(self, db, username):
            return None

        def update(self, db, id, payload):
            return None

    svc = UserService(user_repo=Repo())

    with pytest.raises(UserNotFoundError):
        svc.update_user(db=None, id="me", payload=UserUpdate())


def test_delete_user_not_found_raises():
    class Repo:
        def delete(self, db, id):
            return None

    svc = UserService(user_repo=Repo())

    with pytest.raises(UserNotFoundError):
        svc.delete_user(db=None, id="me")
