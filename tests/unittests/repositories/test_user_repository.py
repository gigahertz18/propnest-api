import pytest
import uuid
from app.repositories.user import user_repo
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import UserRole
from app.core.security import verify_password
from tests.factories import make_user, make_user_model, make_admin_model


class TestUserRepositoryGetAll:
    def test_returns_empty_list_when_no_users(self, db):
        result = user_repo.get_all(db)
        assert result == []

    def test_returns_all_users(self, db):
        make_user_model(db, username="user1", email="user1@example.com")
        make_user_model(db, username="user2", email="user2@example.com")
        result = user_repo.get_all(db)
        assert len(result) == 2

    def test_skip_and_limit(self, db):
        for i in range(5):
            make_user_model(db, username=f"user{i}", email=f"user{i}@example.com")
        result = user_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2


class TestUserRepositoryGetById:
    def test_returns_user_when_found(self, db):
        user = make_user_model(db)
        result = user_repo.get_by_id(db, user.id)
        assert result is not None
        assert result.id == user.id

    def test_returns_none_when_not_found(self, db):
        result = user_repo.get_by_id(db, uuid.uuid4())
        assert result is None


class TestUserRepositoryGetByEmail:
    def test_returns_user_when_found(self, db):
        make_user_model(db, email="found@example.com")
        result = user_repo.get_by_email(db, "found@example.com")
        assert result is not None
        assert result.email == "found@example.com"

    def test_returns_none_when_not_found(self, db):
        result = user_repo.get_by_email(db, "missing@example.com")
        assert result is None


class TestUserRepositoryGetByUsername:
    def test_returns_user_when_found(self, db):
        make_user_model(db, username="findme")
        result = user_repo.get_by_username(db, "findme")
        assert result is not None
        assert result.username == "findme"

    def test_returns_none_when_not_found(self, db):
        result = user_repo.get_by_username(db, "nobody")
        assert result is None


class TestUserRepositoryGetByIdentifier:
    def test_finds_by_email(self, db):
        make_user_model(db, email="byemail@example.com")
        result = user_repo.get_by_identifier(db, "byemail@example.com")
        assert result is not None
        assert result.email == "byemail@example.com"

    def test_finds_by_username(self, db):
        make_user_model(db, username="byusername")
        result = user_repo.get_by_identifier(db, "byusername")
        assert result is not None
        assert result.username == "byusername"

    def test_returns_none_when_not_found(self, db):
        result = user_repo.get_by_identifier(db, "nothere")
        assert result is None


class TestUserRepositoryCreate:
    def test_creates_user_successfully(self, db):
        payload = UserCreate(**make_user())
        result = user_repo.create(db, payload)
        assert result.id is not None
        assert result.email == "testuser@example.com"
        assert result.username == "testuser"
        assert result.role == UserRole.USER
        assert result.is_active is True

    def test_password_is_hashed_on_create(self, db):
        payload = UserCreate(**make_user(password="secret123"))
        result = user_repo.create(db, payload)
        assert result.password_hash != "secret123"
        assert verify_password("secret123", result.password_hash)

    def test_plain_password_not_stored(self, db):
        payload = UserCreate(**make_user(password="mypassword"))
        result = user_repo.create(db, payload)
        assert not hasattr(result, "password")

    def test_default_role_is_user(self, db):
        data = make_user()
        data.pop("role")
        payload = UserCreate(**data)
        result = user_repo.create(db, payload)
        assert result.role == UserRole.USER
    
    def test_create_duplicate_email_raises(self, db):
        user_repo.create(db, UserCreate(**make_user()))
        with pytest.raises(Exception):  # IntegrityError
            user_repo.create(db, UserCreate(**make_user(username="other")))


class TestUserRepositoryUpdate:
    def test_updates_full_name(self, db):
        user = make_user_model(db)
        payload = UserUpdate(full_name="Updated Name")
        result = user_repo.update(db, user.id, payload)
        assert result.full_name == "Updated Name"

    def test_password_is_hashed_on_update(self, db):
        user = make_user_model(db)
        payload = UserUpdate(password="newpassword")
        result = user_repo.update(db, user.id, payload)
        assert verify_password("newpassword", result.password_hash)

    def test_partial_update_does_not_affect_other_fields(self, db):
        user = make_user_model(db, email="original@example.com")
        payload = UserUpdate(full_name="New Name")
        result = user_repo.update(db, user.id, payload)
        assert result.email == "original@example.com"

    def test_returns_none_when_not_found(self, db):
        payload = UserUpdate(full_name="New Name")
        result = user_repo.update(db, uuid.uuid4(), payload)
        assert result is None


class TestUserRepositoryDelete:
    def test_deletes_user_successfully(self, db):
        user = make_user_model(db)
        user_id = user.id
        result = user_repo.delete(db, user_id)
        assert result is not None
        assert user_repo.get_by_id(db, user_id) is None

    def test_returns_none_when_not_found(self, db):
        result = user_repo.delete(db, uuid.uuid4())
        assert result is None


class TestUserRepositoryGetByRole:
    def test_get_admins(self, db):
        make_admin_model(db)
        make_user_model(db, username="regular", email="regular@example.com")
        result = user_repo.get_by_role(db, UserRole.ADMIN)
        assert len(result) == 1
        assert result[0].role == UserRole.ADMIN

    def test_get_regular_users(self, db):
        make_admin_model(db)
        make_user_model(db, username="regular", email="regular@example.com")
        result = user_repo.get_by_role(db, UserRole.USER)
        assert len(result) == 1
        assert result[0].role == UserRole.USER
