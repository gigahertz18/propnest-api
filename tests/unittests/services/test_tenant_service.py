from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.tenant_service import TenantService
from app.models.user import UserRole
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    UserNotFoundError,
    TenantAlreadyLinkedError,
    TenantForbiddenError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo


async def test_tenant_service_delegates_to_repo_methods(mock_db):
    class Repo:
        async def get_all(self, db, skip=0, limit=100):
            return ["t1"]

        async def get_by_id(self, db, id):
            return "byid"

        async def create(self, db, payload):
            return "created"

        async def update(self, db, id, payload):
            return "updated"

        async def delete(self, db, id):
            return "deleted"

        async def get_by_email(self, db, email):
            return "email"

        async def get_by_phone_number(self, db, phone_number):
            return "phone"

        async def get_by_full_name(self, db, full_name, skip=0, limit=100):
            return ["name"]

        async def get_by_occupation(self, db, occupation, skip=0, limit=100):
            return ["occ"]

        async def get_by_date_of_birth(self, db, dob, skip=0, limit=100):
            return ["dob"]

    repo = Repo()
    svc = TenantService(tenant_repo=repo)
    admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

    assert await svc.list_tenants(db=mock_db, current_user=admin) == ["t1"]
    assert await svc.get_tenant(db=mock_db, id=1, current_user=admin) == "byid"
    assert await svc.create_tenant(db=mock_db, payload=None) == "created"
    assert await svc.update_tenant(db=mock_db, id=1, payload=None, current_user=admin) == "updated"
    assert await svc.delete_tenant(db=mock_db, id=1, current_user=admin) == "deleted"
    assert await svc.get_by_email(db=mock_db, email="e") == "email"
    assert await svc.get_by_phone_number(db=mock_db, phone_number="p") == "phone"
    assert await svc.get_by_full_name(db=mock_db, full_name="n") == ["name"]
    assert await svc.get_by_occupation(db=mock_db, occupation="o") == ["occ"]

    assert await svc.get_by_date_of_birth(db=mock_db, date_of_birth=date(2000, 1, 1)) == ["dob"]


async def test_tenant_service_forwards_pagination_defaults(mock_db):
    """Default skip/limit are applied when the caller doesn't specify them,
    and custom values are forwarded unchanged to the repo."""
    captured = {}

    class Repo:
        async def get_by_full_name(self, db, full_name, skip=0, limit=100):
            captured["full_name"] = (skip, limit)
            return []

        async def get_by_occupation(self, db, occupation, skip=0, limit=100):
            captured["occupation"] = (skip, limit)
            return []

        async def get_by_date_of_birth(self, db, dob, skip=0, limit=100):
            captured["dob"] = (skip, limit)
            return []

    svc = TenantService(tenant_repo=Repo())

    await svc.get_by_full_name(db=mock_db, full_name="n")
    await svc.get_by_occupation(db=mock_db, occupation="o")
    await svc.get_by_date_of_birth(db=mock_db, date_of_birth=date(2000, 1, 1))
    assert captured["full_name"] == (0, 100)
    assert captured["occupation"] == (0, 100)
    assert captured["dob"] == (0, 100)

    await svc.get_by_full_name(db=mock_db, full_name="n", skip=10, limit=5)
    assert captured["full_name"] == (10, 5)


class MockTenantRepo(MockCRUDRepo):
    """Adds get_by_user_id on top of MockCRUDRepo, mirroring TenantRepository."""

    async def get_by_user_id(self, db, user_id):
        results = await self._filter_by(user_id=user_id)
        return results[0] if results else None


def _make_tenant(user_id=None):
    return SimpleNamespace(id=uuid4(), user_id=user_id)


def _make_service(tenants=None, users=None) -> TenantService:
    return TenantService(
        tenant_repo=MockTenantRepo(tenants or {}),
        user_repo=MockReadOnlyRepo(users or {}),
    )


@pytest.mark.asyncio
class TestTenantServiceGetByUserId:
    async def test_returns_tenant_when_linked(self, mock_db):
        tenant = _make_tenant(user_id=uuid4())
        svc = _make_service(tenants={tenant.id: tenant})
        result = await svc.get_by_user_id(mock_db, tenant.user_id)
        assert result is tenant

    async def test_returns_none_when_not_linked(self, mock_db):
        svc = _make_service()
        result = await svc.get_by_user_id(mock_db, uuid4())
        assert result is None


@pytest.mark.asyncio
class TestTenantServiceLinkUser:
    async def test_links_unlinked_tenant_to_user(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())
        svc = _make_service(tenants={tenant.id: tenant}, users={user.id: user})

        result = await svc.link_user(mock_db, tenant.id, user.id, current_user=_make_admin())

        assert result.user_id == user.id
        assert mock_db.commit.called

    async def test_relinking_same_user_is_idempotent(self, mock_db):
        user = SimpleNamespace(id=uuid4())
        tenant = _make_tenant(user_id=user.id)
        svc = _make_service(tenants={tenant.id: tenant}, users={user.id: user})

        result = await svc.link_user(mock_db, tenant.id, user.id, current_user=_make_admin())

        assert result.user_id == user.id

    async def test_raises_when_tenant_not_found(self, mock_db):
        user = SimpleNamespace(id=uuid4())
        svc = _make_service(users={user.id: user})

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.link_user(mock_db, uuid4(), user.id, current_user=_make_admin())

    async def test_raises_when_user_not_found(self, mock_db):
        tenant = _make_tenant()
        svc = _make_service(tenants={tenant.id: tenant})

        with pytest.raises(UserNotFoundError):
            await svc.link_user(mock_db, tenant.id, uuid4(), current_user=_make_admin())

    async def test_raises_when_tenant_already_linked_to_different_user(self, mock_db):
        other_user_id = uuid4()
        tenant = _make_tenant(user_id=other_user_id)
        new_user = SimpleNamespace(id=uuid4())
        svc = _make_service(tenants={tenant.id: tenant}, users={new_user.id: new_user})

        with pytest.raises(TenantAlreadyLinkedError):
            await svc.link_user(mock_db, tenant.id, new_user.id, current_user=_make_admin())

    async def test_raises_when_user_already_linked_to_different_tenant(self, mock_db):
        user = SimpleNamespace(id=uuid4())
        already_linked_tenant = _make_tenant(user_id=user.id)
        unlinked_tenant = _make_tenant()
        svc = _make_service(
            tenants={
                already_linked_tenant.id: already_linked_tenant,
                unlinked_tenant.id: unlinked_tenant,
            },
            users={user.id: user},
        )

        with pytest.raises(TenantAlreadyLinkedError):
            await svc.link_user(mock_db, unlinked_tenant.id, user.id, current_user=_make_admin())

    async def test_translates_unique_constraint_violation(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())

        class FailingRepo(MockTenantRepo):
            async def update(self, db, id, payload):
                raise IntegrityError(
                    "UPDATE",
                    {},
                    Exception('duplicate key value violates unique constraint "ix_tenants_user_id"'),
                )

        svc = TenantService(
            tenant_repo=FailingRepo({tenant.id: tenant}),
            user_repo=MockReadOnlyRepo({user.id: user}),
        )

        with pytest.raises(TenantAlreadyLinkedError):
            await svc.link_user(mock_db, tenant.id, user.id, current_user=_make_admin())

        assert mock_db.rollback.called

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())

        class FailingRepo(MockTenantRepo):
            async def update(self, db, id, payload):
                raise IntegrityError("UPDATE", {}, Exception("some unrelated constraint violation"))

        svc = TenantService(
            tenant_repo=FailingRepo({tenant.id: tenant}),
            user_repo=MockReadOnlyRepo({user.id: user}),
        )

        with pytest.raises(IntegrityError):
            await svc.link_user(mock_db, tenant.id, user.id, current_user=_make_admin())

    async def test_current_user_is_required(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())
        svc = _make_service(tenants={tenant.id: tenant}, users={user.id: user})
        with pytest.raises(TypeError):
            await svc.link_user(mock_db, tenant.id, user.id)


@pytest.mark.asyncio
class TestTenantServiceUnlinkUser:
    async def test_unlinks_linked_tenant(self, mock_db):
        tenant = _make_tenant(user_id=uuid4())
        svc = _make_service(tenants={tenant.id: tenant})

        result = await svc.unlink_user(mock_db, tenant.id, current_user=_make_admin())

        assert result.user_id is None
        assert mock_db.commit.called

    async def test_unlinking_already_unlinked_tenant_is_idempotent(self, mock_db):
        tenant = _make_tenant()
        svc = _make_service(tenants={tenant.id: tenant})

        result = await svc.unlink_user(mock_db, tenant.id, current_user=_make_admin())

        assert result.user_id is None

    async def test_raises_when_tenant_not_found(self, mock_db):
        svc = _make_service()

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.unlink_user(mock_db, uuid4(), current_user=_make_admin())

    async def test_current_user_is_required(self, mock_db):
        tenant = _make_tenant(user_id=uuid4())
        svc = _make_service(tenants={tenant.id: tenant})
        with pytest.raises(TypeError):
            await svc.unlink_user(mock_db, tenant.id)


def _make_admin():
    return SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)


def _make_manager(manager_id=None):
    return SimpleNamespace(id=manager_id or uuid4(), role=UserRole.MANAGER)


class MockOwnershipTenantRepo(MockTenantRepo):
    """Extends MockTenantRepo with manager-ownership primitives, driven by
    a simple owner-set map rather than real SQL — the actual EXISTS-based
    query semantics are covered by the repository's own integration tests
    against a real DB; this only needs to exercise TenantService's control
    flow (does it call the right repo method, raise the right exception)."""

    def __init__(self, records=None, owners: dict | None = None):
        super().__init__(records or {})
        # tenant_id -> set of manager_ids who own it. Absent/empty = unclaimed.
        self.owners = owners or {}

    async def is_accessible_by_manager(self, db, tenant_id, manager_id):
        owning_managers = self.owners.get(tenant_id)
        if not owning_managers:
            return True  # unclaimed tenant — any manager may act on it
        return manager_id in owning_managers

    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return [
            t
            for tid, t in self.records.items()
            if not self.owners.get(tid) or manager_id in self.owners.get(tid, set())
        ]


@pytest.mark.asyncio
class TestTenantServiceAuthorization:
    async def test_admin_bypasses_ownership_check(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = TenantService(tenant_repo=repo)
        admin = _make_admin()

        result = await svc.get_tenant(mock_db, tenant.id, current_user=admin)
        assert result is tenant

    async def test_manager_can_access_unclaimed_tenant(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant})
        svc = TenantService(tenant_repo=repo)
        manager = _make_manager()

        result = await svc.get_tenant(mock_db, tenant.id, current_user=manager)
        assert result is tenant

    async def test_manager_can_access_own_tenant(self, mock_db):
        tenant = _make_tenant()
        manager = _make_manager()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {manager.id}})
        svc = TenantService(tenant_repo=repo)

        result = await svc.get_tenant(mock_db, tenant.id, current_user=manager)
        assert result is tenant

    async def test_manager_cannot_access_another_managers_tenant(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = TenantService(tenant_repo=repo)
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.get_tenant(mock_db, tenant.id, current_user=manager)

    async def test_update_tenant_enforces_authorization(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = TenantService(tenant_repo=repo)
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.update_tenant(mock_db, tenant.id, payload={}, current_user=manager)

    async def test_delete_tenant_enforces_authorization(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = TenantService(tenant_repo=repo)
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.delete_tenant(mock_db, tenant.id, current_user=manager)

    async def test_list_tenants_scopes_to_manager_ownership(self, mock_db):
        owned = _make_tenant()
        unowned = _make_tenant()
        manager = _make_manager()
        repo = MockOwnershipTenantRepo(
            {owned.id: owned, unowned.id: unowned},
            owners={owned.id: {manager.id}, unowned.id: {uuid4()}},
        )
        svc = TenantService(tenant_repo=repo)

        result = await svc.list_tenants(mock_db, current_user=manager)
        assert result == [owned]

    async def test_list_tenants_admin_sees_everything(self, mock_db):
        t1, t2 = _make_tenant(), _make_tenant()
        repo = MockCRUDRepo({t1.id: t1, t2.id: t2})
        svc = TenantService(tenant_repo=repo)
        admin = _make_admin()

        result = await svc.list_tenants(mock_db, current_user=admin)
        assert result == [t1, t2]

    async def test_link_user_enforces_authorization(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = TenantService(tenant_repo=repo, user_repo=MockReadOnlyRepo({user.id: user}))
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.link_user(mock_db, tenant.id, user.id, current_user=manager)
