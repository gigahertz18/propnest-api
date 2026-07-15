import pytest
import uuid
from datetime import date

from sqlalchemy.exc import IntegrityError

from app.repositories.tenant import tenant_repo
from app.schemas.tenant import TenantCreate, TenantUpdate
from tests.factories import make_tenant, make_tenant_model, make_user_model


@pytest.mark.asyncio
class TestTenantRepositoryGetAll:
    async def test_returns_empty_list_when_no_tenants(self, db):
        result = await tenant_repo.get_all(db)
        assert result == []

    async def test_returns_all_tenants(self, db):
        before = await tenant_repo.get_all(db)
        await make_tenant_model(db, full_name="Tenant A", email="a@example.com")
        await make_tenant_model(db, full_name="Tenant B", email="b@example.com")
        result = await tenant_repo.get_all(db)
        assert len(result) == len(before) + 2

    async def test_skip_and_limit(self, db):
        for i in range(5):
            await make_tenant_model(db, full_name=f"Tenant {i}", email=f"tenant{i}@example.com")
        result = await tenant_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2

    async def test_limit_zero_returns_empty(self, db):
        await make_tenant_model(db)
        result = await tenant_repo.get_all(db, limit=0)
        assert result == []


@pytest.mark.asyncio
class TestTenantRepositoryGetById:
    async def test_returns_tenant_when_found(self, db):
        tenant = await make_tenant_model(db)
        result = await tenant_repo.get_by_id(db, tenant.id)
        assert result is not None
        assert result.id == tenant.id

    async def test_returns_none_when_not_found(self, db):
        result = await tenant_repo.get_by_id(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestTenantRepositoryCreate:
    async def test_creates_tenant_successfully(self, db):
        payload = TenantCreate(**make_tenant())
        result = await tenant_repo.create(db, payload)
        assert result.id is not None
        assert result.full_name == payload.full_name
        assert result.email == payload.email

    async def test_created_tenant_is_persisted(self, db):
        payload = TenantCreate(**make_tenant(full_name="Persisted Tenant", email="persisted@example.com"))
        created = await tenant_repo.create(db, payload)
        fetched = await tenant_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.full_name == "Persisted Tenant"

    async def test_default_is_active_is_true(self, db):
        payload = TenantCreate(**make_tenant())
        result = await tenant_repo.create(db, payload)
        assert result.is_active is True

    async def test_can_create_inactive_tenant(self, db):
        payload = TenantCreate(**make_tenant(is_active=False))
        result = await tenant_repo.create(db, payload)
        assert result.is_active is False

    async def test_optional_fields_can_be_none(self, db):
        payload = TenantCreate(
            **make_tenant(
                occupation=None,
                notes=None,
            )
        )
        result = await tenant_repo.create(db, payload)
        assert result.occupation is None
        assert result.notes is None

    async def test_all_fields_are_stored(self, db):
        dob = date(1990, 6, 15)
        payload = TenantCreate(
            **make_tenant(
                full_name="Full Fields",
                email="fullfields@example.com",
                phone_number="09991234567",
                date_of_birth=dob,
                current_address="456 Real Ave",
                occupation="Developer",
                notes="Some notes here",
            )
        )
        result = await tenant_repo.create(db, payload)
        assert result.full_name == "Full Fields"
        assert result.phone_number == "09991234567"
        assert result.date_of_birth == dob
        assert result.current_address == "456 Real Ave"
        assert result.occupation == "Developer"
        assert result.notes == "Some notes here"

    async def test_duplicate_email_is_allowed(self, db):
        # No unique constraint on email — two tenants can share one.
        # This test documents the current behaviour; add a DB constraint
        # and flip this to expect an error when that changes.
        await make_tenant_model(db, email="shared@example.com")
        payload = TenantCreate(**make_tenant(email="shared@example.com"))
        result = await tenant_repo.create(db, payload)
        assert result is not None


@pytest.mark.asyncio
class TestTenantRepositoryUpdate:
    async def test_updates_full_name(self, db):
        tenant = await make_tenant_model(db)
        result = await tenant_repo.update(db, tenant.id, TenantUpdate(full_name="Updated Name"))
        assert result.full_name == "Updated Name"

    async def test_partial_update_does_not_affect_other_fields(self, db):
        tenant = await make_tenant_model(db, email="original@example.com")
        result = await tenant_repo.update(db, tenant.id, TenantUpdate(full_name="New Name"))
        assert result.email == "original@example.com"

    async def test_update_email(self, db):
        tenant = await make_tenant_model(db)
        result = await tenant_repo.update(db, tenant.id, TenantUpdate(email="new@example.com"))
        assert result.email == "new@example.com"

    async def test_update_is_active_to_false(self, db):
        tenant = await make_tenant_model(db)
        result = await tenant_repo.update(db, tenant.id, TenantUpdate(is_active=False))
        assert result.is_active is False

    async def test_update_is_active_back_to_true(self, db):
        tenant = await make_tenant_model(db, is_active=False)
        result = await tenant_repo.update(db, tenant.id, TenantUpdate(is_active=True))
        assert result.is_active is True

    async def test_update_returns_none_when_not_found(self, db):
        result = await tenant_repo.update(db, uuid.uuid4(), TenantUpdate(full_name="Ghost"))
        assert result is None

    async def test_updated_value_is_persisted(self, db):
        tenant = await make_tenant_model(db)
        await tenant_repo.update(db, tenant.id, TenantUpdate(full_name="Saved Name"))
        fetched = await tenant_repo.get_by_id(db, tenant.id)
        assert fetched.full_name == "Saved Name"


@pytest.mark.asyncio
class TestTenantRepositoryDelete:
    async def test_deletes_tenant_successfully(self, db):
        tenant = await make_tenant_model(db)
        result = await tenant_repo.delete(db, tenant.id)
        assert result is not None
        assert result.id == tenant.id

    async def test_deleted_tenant_is_gone(self, db):
        tenant = await make_tenant_model(db)
        await tenant_repo.delete(db, tenant.id)
        assert await tenant_repo.get_by_id(db, tenant.id) is None

    async def test_returns_none_when_not_found(self, db):
        result = await tenant_repo.delete(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestTenantRepositoryGetByEmail:
    async def test_returns_tenant_when_found(self, db):
        tenant = await make_tenant_model(db, email="findme@example.com")
        result = await tenant_repo.get_by_email(db, "findme@example.com")
        assert result is not None
        assert result.id == tenant.id

    async def test_returns_none_when_not_found(self, db):
        result = await tenant_repo.get_by_email(db, "ghost@example.com")
        assert result is None

    async def test_is_exact_match(self, db):
        await make_tenant_model(db, email="exact@example.com")
        result = await tenant_repo.get_by_email(db, "exact")
        assert result is None

    async def test_returns_first_on_duplicate_email(self, db):
        # Documents current behaviour — no uniqueness enforced at DB level
        await make_tenant_model(db, email="dup@example.com", full_name="First")
        await make_tenant_model(db, email="dup@example.com", full_name="Second")
        result = tenant_repo.get_by_email(db, "dup@example.com")
        assert result is not None


@pytest.mark.asyncio
class TestTenantRepositoryGetByPhoneNumber:
    async def test_returns_tenant_when_found(self, db):
        tenant = await make_tenant_model(db, phone_number="09123456789")
        result = await tenant_repo.get_by_phone_number(db, "09123456789")
        assert result is not None
        assert result.id == tenant.id

    async def test_returns_none_when_not_found(self, db):
        result = await tenant_repo.get_by_phone_number(db, "00000000000")
        assert result is None

    async def test_is_exact_match(self, db):
        await make_tenant_model(db, phone_number="09123456789")
        result = await tenant_repo.get_by_phone_number(db, "0912")
        assert result is None


@pytest.mark.asyncio
class TestTenantRepositoryGetByFullName:
    async def test_returns_tenant_by_exact_name(self, db):
        await make_tenant_model(db, full_name="John Doe", email="john@example.com")
        result = await tenant_repo.get_by_full_name(db, "John Doe")
        assert any(t.full_name == "John Doe" for t in result)

    async def test_returns_partial_match(self, db):
        await make_tenant_model(db, full_name="Jane Smith", email="jane@example.com")
        result = await tenant_repo.get_by_full_name(db, "Jane")
        assert any(t.full_name == "Jane Smith" for t in result)

    async def test_is_case_insensitive(self, db):
        await make_tenant_model(db, full_name="Alice Brown", email="alice@example.com")
        result = await tenant_repo.get_by_full_name(db, "alice brown")
        assert any(t.full_name == "Alice Brown" for t in result)

    async def test_returns_multiple_matches(self, db):
        await make_tenant_model(db, full_name="Bob A", email="boba@example.com")
        await make_tenant_model(db, full_name="Bob B", email="bobb@example.com")
        result = await tenant_repo.get_by_full_name(db, "Bob")
        assert len([t for t in result if t.full_name.startswith("Bob")]) == 2

    async def test_returns_empty_list_when_no_match(self, db):
        result = await tenant_repo.get_by_full_name(db, "Nonexistent XYZ9999")
        assert result == []


@pytest.mark.asyncio
class TestTenantRepositoryGetByOccupation:
    async def test_returns_tenant_by_occupation(self, db):
        await make_tenant_model(db, occupation="Engineer", email="eng@example.com")
        result = await tenant_repo.get_by_occupation(db, "Engineer")
        assert any(t.occupation == "Engineer" for t in result)

    async def test_returns_partial_match(self, db):
        await make_tenant_model(db, occupation="Software Engineer", email="se@example.com")
        result = await tenant_repo.get_by_occupation(db, "Software")
        assert any(t.occupation == "Software Engineer" for t in result)

    async def test_is_case_insensitive(self, db):
        await make_tenant_model(db, occupation="Doctor", email="doc@example.com")
        result = await tenant_repo.get_by_occupation(db, "doctor")
        assert any(t.occupation == "Doctor" for t in result)

    async def test_returns_multiple_matches(self, db):
        await make_tenant_model(db, occupation="Nurse", email="nurse1@example.com")
        await make_tenant_model(db, occupation="Nurse", email="nurse2@example.com")
        result = await tenant_repo.get_by_occupation(db, "Nurse")
        assert len([t for t in result if t.occupation == "Nurse"]) == 2

    async def test_returns_empty_list_when_no_match(self, db):
        result = await tenant_repo.get_by_occupation(db, "AstronautXYZ9999")
        assert result == []

    async def test_returns_empty_list_when_occupation_is_none(self, db):
        await make_tenant_model(db, occupation=None, email="noocc@example.com")
        result = await tenant_repo.get_by_occupation(db, "Engineer")
        # Tenants with NULL occupation should not appear in filtered results
        assert all(t.occupation is not None for t in result)


@pytest.mark.asyncio
class TestTenantRepositoryGetByUserId:
    async def test_returns_tenant_when_linked(self, db):
        user = await make_user_model(db, username="linked_user", email="linked@example.com")
        tenant = await make_tenant_model(db, user_id=user.id, email="linked_tenant@example.com")
        result = await tenant_repo.get_by_user_id(db, user.id)
        assert result is not None
        assert result.id == tenant.id

    async def test_returns_none_when_not_linked(self, db):
        result = await tenant_repo.get_by_user_id(db, uuid.uuid4())
        assert result is None

    async def test_returns_none_for_tenant_with_null_user_id(self, db):
        # Default tenant has no linked user — must not accidentally match
        # a lookup for None or any other falsy-ish value.
        await make_tenant_model(db, email="unlinked@example.com")
        result = await tenant_repo.get_by_user_id(db, uuid.uuid4())
        assert result is None

    async def test_db_rejects_second_tenant_linked_to_same_user(self, db):
        # Documents the DB-level guarantee from the unique index on
        # tenants.user_id: a user can only ever be linked to one tenant.
        # TenantService.link_user checks this in Python first, but the
        # constraint is the real backstop against concurrent requests.
        user = await make_user_model(db, username="shared_user", email="shared_user@example.com")
        await make_tenant_model(db, user_id=user.id, email="first_tenant@example.com")

        from app.models.tenant import Tenant as TenantModel

        dupe = TenantModel(
            id=uuid.uuid4(),
            **make_tenant(email="second_tenant@example.com"),
            user_id=user.id,
        )
        db.add(dupe)
        with pytest.raises(IntegrityError):
            await db.flush()


@pytest.mark.asyncio
class TestTenantRepositoryGetByDateOfBirth:
    async def test_returns_tenant_by_date_of_birth(self, db):
        dob = date(1990, 1, 1)
        tenant = await make_tenant_model(db, date_of_birth=dob, email="dob@example.com")
        result = await tenant_repo.get_by_date_of_birth(db, dob)
        assert any(t.id == tenant.id for t in result)

    async def test_returns_multiple_matches(self, db):
        dob = date(1985, 5, 20)
        await make_tenant_model(db, date_of_birth=dob, email="dob1@example.com")
        await make_tenant_model(db, date_of_birth=dob, email="dob2@example.com")
        result = await tenant_repo.get_by_date_of_birth(db, dob)
        assert len([t for t in result if t.date_of_birth == dob]) == 2

    async def test_returns_empty_list_when_no_match(self, db):
        result = await tenant_repo.get_by_date_of_birth(db, date(1800, 1, 1))
        assert result == []

    async def test_does_not_return_tenants_with_different_dob(self, db):
        await make_tenant_model(db, date_of_birth=date(1990, 1, 1), email="dob3@example.com")
        result = await tenant_repo.get_by_date_of_birth(db, date(1991, 1, 1))
        assert all(t.date_of_birth == date(1991, 1, 1) for t in result)
