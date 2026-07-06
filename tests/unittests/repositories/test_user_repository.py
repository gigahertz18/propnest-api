import asyncio
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.repositories.user import user_repo
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import UserRole
from app.core.security import verify_password
from tests.factories import make_user, make_user_model, make_admin_model


@pytest.mark.asyncio
class TestUserRepositoryGetAll:
    async def test_returns_empty_list_when_no_users(self, db):
        result = await user_repo.get_all(db)
        assert result == []

    async def test_returns_all_users(self, db):
        await make_user_model(db, username="user1", email="user1@example.com")
        await make_user_model(db, username="user2", email="user2@example.com")
        result = await user_repo.get_all(db)
        assert len(result) == 2

    async def test_skip_and_limit(self, db):
        for i in range(5):
            await make_user_model(db, username=f"user{i}", email=f"user{i}@example.com")
        result = await user_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2


@pytest.mark.asyncio
class TestUserRepositoryGetById:
    async def test_returns_user_when_found(self, db):
        user = await make_user_model(db)
        result = await user_repo.get_by_id(db, user.id)
        assert result is not None
        assert result.id == user.id

    async def test_returns_none_when_not_found(self, db):
        result = await user_repo.get_by_id(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestUserRepositoryGetByEmail:
    async def test_returns_user_when_found(self, db):
        await make_user_model(db, email="found@example.com")
        result = await user_repo.get_by_email(db, "found@example.com")
        assert result is not None
        assert result.email == "found@example.com"

    async def test_returns_none_when_not_found(self, db):
        result = await user_repo.get_by_email(db, "missing@example.com")
        assert result is None


@pytest.mark.asyncio
class TestUserRepositoryGetByUsername:
    async def test_returns_user_when_found(self, db):
        await make_user_model(db, username="findme")
        result = await user_repo.get_by_username(db, "findme")
        assert result is not None
        assert result.username == "findme"

    async def test_returns_none_when_not_found(self, db):
        result = await user_repo.get_by_username(db, "nobody")
        assert result is None


@pytest.mark.asyncio
class TestUserRepositoryGetByIdentifier:
    async def test_finds_by_email(self, db):
        await make_user_model(db, email="byemail@example.com")
        result = await user_repo.get_by_identifier(db, "byemail@example.com")
        assert result is not None
        assert result.email == "byemail@example.com"

    async def test_finds_by_username(self, db):
        await make_user_model(db, username="byusername")
        result = await user_repo.get_by_identifier(db, "byusername")
        assert result is not None
        assert result.username == "byusername"

    async def test_returns_none_when_not_found(self, db):
        result = await user_repo.get_by_identifier(db, "nothere")
        assert result is None


@pytest.mark.asyncio
class TestUserRepositoryCreate:
    async def test_creates_user_successfully(self, db):
        payload = UserCreate(**make_user())
        result = await user_repo.create(db, payload)
        assert result.id is not None
        assert result.email == "testuser@example.com"
        assert result.username == "testuser"
        assert result.role == UserRole.USER
        assert result.is_active is True

    async def test_password_is_hashed_on_create(self, db):
        payload = UserCreate(**make_user(password="secret123"))
        result = await user_repo.create(db, payload)
        assert result.password_hash != "secret123"
        assert verify_password("secret123", result.password_hash)

    async def test_plain_password_not_stored(self, db):
        payload = UserCreate(**make_user(password="mypassword"))
        result = await user_repo.create(db, payload)
        assert not hasattr(result, "password")

    async def test_default_role_is_user(self, db):
        data = make_user()
        data.pop("role")
        payload = UserCreate(**data)
        result = await user_repo.create(db, payload)
        assert result.role == UserRole.USER

    async def test_create_duplicate_email_raises(self, db):
        await user_repo.create(db, UserCreate(**make_user()))
        with pytest.raises(Exception):  # IntegrityError
            await user_repo.create(db, UserCreate(**make_user(username="other")))

    async def test_create_normalizes_username_and_email(self, db):
        payload = UserCreate(**make_user(username="TestUser", email="Test@Example.COM"))
        result = await user_repo.create(db, payload)
        assert result.username == "testuser"
        assert result.email == "test@example.com"

    async def test_concurrent_create_with_same_email_fails_once(self, db):
        engine = create_async_engine(settings.DATABASE_URL)
        SessionLocal = sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        success = failure = 0

        async def create_user():
            async with SessionLocal() as session:
                try:
                    await user_repo.create(
                        session, UserCreate(**make_user(username="racer", email="racer@example.com"))
                    )
                    await session.commit()
                    return True
                except IntegrityError:
                    await session.rollback()
                    return False

        try:
            results = await asyncio.gather(
                create_user(),
                create_user(),
            )

            success = sum(results)
            failure = len(results) - success

        finally:
            # cleanup created user so subsequent tests
            # are not affected by rows inserted outside the test transaction.
            async with SessionLocal() as cleanup_session:
                user = await user_repo.get_by_email(cleanup_session, "racer@example.com")
                if user:
                    await cleanup_session.delete(user)
                    await cleanup_session.commit()

        assert success == 1
        assert failure == 1


@pytest.mark.asyncio
class TestUserRepositoryUpdate:
    async def test_updates_full_name(self, db):
        user = await make_user_model(db)
        payload = UserUpdate(full_name="Updated Name")
        result = await user_repo.update(db, user.id, payload)
        assert result.full_name == "Updated Name"

    async def test_password_is_hashed_on_update(self, db):
        user = await make_user_model(db)
        payload = UserUpdate(password="newpassword")
        result = await user_repo.update(db, user.id, payload)
        assert verify_password("newpassword", result.password_hash)

    async def test_partial_update_does_not_affect_other_fields(self, db):
        user = await make_user_model(db, email="original@example.com")
        payload = UserUpdate(full_name="New Name")
        result = await user_repo.update(db, user.id, payload)
        assert result.email == "original@example.com"

    async def test_update_normalizes_username_and_email(self, db):
        user = await make_user_model(db, username="OriginalUser", email="Original@Example.COM")
        payload = UserUpdate(username="UpdatedUser", email="Updated@Example.COM")
        result = await user_repo.update(db, user.id, payload)
        assert result.username == "updateduser"
        assert result.email == "updated@example.com"

    async def test_returns_none_when_not_found(self, db):
        payload = UserUpdate(full_name="New Name")
        result = await user_repo.update(db, uuid.uuid4(), payload)
        assert result is None


@pytest.mark.asyncio
class TestUserRepositoryDelete:
    async def test_deletes_user_successfully(self, db):
        user = await make_user_model(db)
        user_id = user.id
        result = await user_repo.delete(db, user_id)
        assert result is not None
        assert await user_repo.get_by_id(db, user_id) is None

    async def test_returns_none_when_not_found(self, db):
        result = await user_repo.delete(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestUserRepositoryGetByRole:
    async def test_get_admins(self, db):
        await make_admin_model(db)
        await make_user_model(db, username="regular", email="regular@example.com")
        result = await user_repo.get_by_role(db, UserRole.ADMIN)
        assert len(result) == 1
        assert result[0].role == UserRole.ADMIN

    async def test_get_regular_users(self, db):
        await make_admin_model(db)
        await make_user_model(db, username="regular", email="regular@example.com")
        result = await user_repo.get_by_role(db, UserRole.USER)
        assert len(result) == 1
        assert result[0].role == UserRole.USER
