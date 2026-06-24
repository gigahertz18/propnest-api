import uuid
from datetime import date

from app.repositories.tenant import tenant_repo
from app.schemas.tenant import TenantCreate, TenantUpdate
from tests.factories import make_tenant, make_tenant_model


class TestTenantRepositoryGetAll:
    def test_returns_empty_list_when_no_tenants(self, db):
        result = tenant_repo.get_all(db)
        assert result == []

    def test_returns_all_tenants(self, db):
        before = tenant_repo.get_all(db)
        make_tenant_model(db, full_name="Tenant A", email="a@example.com")
        make_tenant_model(db, full_name="Tenant B", email="b@example.com")
        result = tenant_repo.get_all(db)
        assert len(result) == len(before) + 2

    def test_skip_and_limit(self, db):
        for i in range(5):
            make_tenant_model(db, full_name=f"Tenant {i}", email=f"tenant{i}@example.com")
        result = tenant_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2

    def test_limit_zero_returns_empty(self, db):
        make_tenant_model(db)
        result = tenant_repo.get_all(db, limit=0)
        assert result == []


class TestTenantRepositoryGetById:
    def test_returns_tenant_when_found(self, db):
        tenant = make_tenant_model(db)
        result = tenant_repo.get_by_id(db, tenant.id)
        assert result is not None
        assert result.id == tenant.id

    def test_returns_none_when_not_found(self, db):
        result = tenant_repo.get_by_id(db, uuid.uuid4())
        assert result is None


class TestTenantRepositoryCreate:
    def test_creates_tenant_successfully(self, db):
        payload = TenantCreate(**make_tenant())
        result = tenant_repo.create(db, payload)
        assert result.id is not None
        assert result.full_name == payload.full_name
        assert result.email == payload.email

    def test_created_tenant_is_persisted(self, db):
        payload = TenantCreate(**make_tenant(full_name="Persisted Tenant", email="persisted@example.com"))
        created = tenant_repo.create(db, payload)
        fetched = tenant_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.full_name == "Persisted Tenant"

    def test_default_is_active_is_true(self, db):
        payload = TenantCreate(**make_tenant())
        result = tenant_repo.create(db, payload)
        assert result.is_active is True

    def test_can_create_inactive_tenant(self, db):
        payload = TenantCreate(**make_tenant(is_active=False))
        result = tenant_repo.create(db, payload)
        assert result.is_active is False

    def test_optional_fields_can_be_none(self, db):
        payload = TenantCreate(
            **make_tenant(
                occupation=None,
                notes=None,
            )
        )
        result = tenant_repo.create(db, payload)
        assert result.occupation is None
        assert result.notes is None

    def test_all_fields_are_stored(self, db):
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
        result = tenant_repo.create(db, payload)
        assert result.full_name == "Full Fields"
        assert result.phone_number == "09991234567"
        assert result.date_of_birth == dob
        assert result.current_address == "456 Real Ave"
        assert result.occupation == "Developer"
        assert result.notes == "Some notes here"

    def test_duplicate_email_is_allowed(self, db):
        # No unique constraint on email — two tenants can share one.
        # This test documents the current behaviour; add a DB constraint
        # and flip this to expect an error when that changes.
        make_tenant_model(db, email="shared@example.com")
        payload = TenantCreate(**make_tenant(email="shared@example.com"))
        result = tenant_repo.create(db, payload)
        assert result is not None


class TestTenantRepositoryUpdate:
    def test_updates_full_name(self, db):
        tenant = make_tenant_model(db)
        result = tenant_repo.update(db, tenant.id, TenantUpdate(full_name="Updated Name"))
        assert result.full_name == "Updated Name"

    def test_partial_update_does_not_affect_other_fields(self, db):
        tenant = make_tenant_model(db, email="original@example.com")
        result = tenant_repo.update(db, tenant.id, TenantUpdate(full_name="New Name"))
        assert result.email == "original@example.com"

    def test_update_email(self, db):
        tenant = make_tenant_model(db)
        result = tenant_repo.update(db, tenant.id, TenantUpdate(email="new@example.com"))
        assert result.email == "new@example.com"

    def test_update_is_active_to_false(self, db):
        tenant = make_tenant_model(db)
        result = tenant_repo.update(db, tenant.id, TenantUpdate(is_active=False))
        assert result.is_active is False

    def test_update_is_active_back_to_true(self, db):
        tenant = make_tenant_model(db, is_active=False)
        result = tenant_repo.update(db, tenant.id, TenantUpdate(is_active=True))
        assert result.is_active is True

    def test_update_returns_none_when_not_found(self, db):
        result = tenant_repo.update(db, uuid.uuid4(), TenantUpdate(full_name="Ghost"))
        assert result is None

    def test_updated_value_is_persisted(self, db):
        tenant = make_tenant_model(db)
        tenant_repo.update(db, tenant.id, TenantUpdate(full_name="Saved Name"))
        fetched = tenant_repo.get_by_id(db, tenant.id)
        assert fetched.full_name == "Saved Name"


class TestTenantRepositoryDelete:
    def test_deletes_tenant_successfully(self, db):
        tenant = make_tenant_model(db)
        result = tenant_repo.delete(db, tenant.id)
        assert result is not None
        assert result.id == tenant.id

    def test_deleted_tenant_is_gone(self, db):
        tenant = make_tenant_model(db)
        tenant_repo.delete(db, tenant.id)
        assert tenant_repo.get_by_id(db, tenant.id) is None

    def test_returns_none_when_not_found(self, db):
        result = tenant_repo.delete(db, uuid.uuid4())
        assert result is None


class TestTenantRepositoryGetByEmail:
    def test_returns_tenant_when_found(self, db):
        tenant = make_tenant_model(db, email="findme@example.com")
        result = tenant_repo.get_by_email(db, "findme@example.com")
        assert result is not None
        assert result.id == tenant.id

    def test_returns_none_when_not_found(self, db):
        result = tenant_repo.get_by_email(db, "ghost@example.com")
        assert result is None

    def test_is_exact_match(self, db):
        make_tenant_model(db, email="exact@example.com")
        result = tenant_repo.get_by_email(db, "exact")
        assert result is None

    def test_returns_first_on_duplicate_email(self, db):
        # Documents current behaviour — no uniqueness enforced at DB level
        make_tenant_model(db, email="dup@example.com", full_name="First")
        make_tenant_model(db, email="dup@example.com", full_name="Second")
        result = tenant_repo.get_by_email(db, "dup@example.com")
        assert result is not None


class TestTenantRepositoryGetByPhoneNumber:
    def test_returns_tenant_when_found(self, db):
        tenant = make_tenant_model(db, phone_number="09123456789")
        result = tenant_repo.get_by_phone_number(db, "09123456789")
        assert result is not None
        assert result.id == tenant.id

    def test_returns_none_when_not_found(self, db):
        result = tenant_repo.get_by_phone_number(db, "00000000000")
        assert result is None

    def test_is_exact_match(self, db):
        make_tenant_model(db, phone_number="09123456789")
        result = tenant_repo.get_by_phone_number(db, "0912")
        assert result is None


class TestTenantRepositoryGetByFullName:
    def test_returns_tenant_by_exact_name(self, db):
        make_tenant_model(db, full_name="John Doe", email="john@example.com")
        result = tenant_repo.get_by_full_name(db, "John Doe")
        assert any(t.full_name == "John Doe" for t in result)

    def test_returns_partial_match(self, db):
        make_tenant_model(db, full_name="Jane Smith", email="jane@example.com")
        result = tenant_repo.get_by_full_name(db, "Jane")
        assert any(t.full_name == "Jane Smith" for t in result)

    def test_is_case_insensitive(self, db):
        make_tenant_model(db, full_name="Alice Brown", email="alice@example.com")
        result = tenant_repo.get_by_full_name(db, "alice brown")
        assert any(t.full_name == "Alice Brown" for t in result)

    def test_returns_multiple_matches(self, db):
        make_tenant_model(db, full_name="Bob A", email="boba@example.com")
        make_tenant_model(db, full_name="Bob B", email="bobb@example.com")
        result = tenant_repo.get_by_full_name(db, "Bob")
        assert len([t for t in result if t.full_name.startswith("Bob")]) == 2

    def test_returns_empty_list_when_no_match(self, db):
        result = tenant_repo.get_by_full_name(db, "Nonexistent XYZ9999")
        assert result == []


class TestTenantRepositoryGetByOccupation:
    def test_returns_tenant_by_occupation(self, db):
        make_tenant_model(db, occupation="Engineer", email="eng@example.com")
        result = tenant_repo.get_by_occupation(db, "Engineer")
        assert any(t.occupation == "Engineer" for t in result)

    def test_returns_partial_match(self, db):
        make_tenant_model(db, occupation="Software Engineer", email="se@example.com")
        result = tenant_repo.get_by_occupation(db, "Software")
        assert any(t.occupation == "Software Engineer" for t in result)

    def test_is_case_insensitive(self, db):
        make_tenant_model(db, occupation="Doctor", email="doc@example.com")
        result = tenant_repo.get_by_occupation(db, "doctor")
        assert any(t.occupation == "Doctor" for t in result)

    def test_returns_multiple_matches(self, db):
        make_tenant_model(db, occupation="Nurse", email="nurse1@example.com")
        make_tenant_model(db, occupation="Nurse", email="nurse2@example.com")
        result = tenant_repo.get_by_occupation(db, "Nurse")
        assert len([t for t in result if t.occupation == "Nurse"]) == 2

    def test_returns_empty_list_when_no_match(self, db):
        result = tenant_repo.get_by_occupation(db, "AstronautXYZ9999")
        assert result == []

    def test_returns_empty_list_when_occupation_is_none(self, db):
        make_tenant_model(db, occupation=None, email="noocc@example.com")
        result = tenant_repo.get_by_occupation(db, "Engineer")
        # Tenants with NULL occupation should not appear in filtered results
        assert all(t.occupation is not None for t in result)


class TestTenantRepositoryGetByDateOfBirth:
    def test_returns_tenant_by_date_of_birth(self, db):
        dob = date(1990, 1, 1)
        tenant = make_tenant_model(db, date_of_birth=dob, email="dob@example.com")
        result = tenant_repo.get_by_date_of_birth(db, dob)
        assert any(t.id == tenant.id for t in result)

    def test_returns_multiple_matches(self, db):
        dob = date(1985, 5, 20)
        make_tenant_model(db, date_of_birth=dob, email="dob1@example.com")
        make_tenant_model(db, date_of_birth=dob, email="dob2@example.com")
        result = tenant_repo.get_by_date_of_birth(db, dob)
        assert len([t for t in result if t.date_of_birth == dob]) == 2

    def test_returns_empty_list_when_no_match(self, db):
        result = tenant_repo.get_by_date_of_birth(db, date(1800, 1, 1))
        assert result == []

    def test_does_not_return_tenants_with_different_dob(self, db):
        make_tenant_model(db, date_of_birth=date(1990, 1, 1), email="dob3@example.com")
        result = tenant_repo.get_by_date_of_birth(db, date(1991, 1, 1))
        assert all(t.date_of_birth == date(1991, 1, 1) for t in result)
