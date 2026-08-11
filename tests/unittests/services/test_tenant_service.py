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
    TenantAlreadyExistsError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_tenant


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

        async def count_all(self, db):
            return 1

    repo = Repo()
    svc = TenantService(tenant_repo=repo)
    admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

    list_result = await svc.list_tenants(db=mock_db, current_user=admin)
    assert list_result.items == ["t1"]
    assert list_result.total == 1
    assert await svc.get_tenant(db=mock_db, id=1, current_user=admin) == "byid"
    assert await svc.create_tenant(db=mock_db, payload=None, current_user=admin) == "created"
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
    """Adds get_by_user_id/get_by_email on top of MockCRUDRepo, mirroring TenantRepository."""

    async def get_by_user_id(self, db, user_id):
        results = await self._filter_by(user_id=user_id)
        return results[0] if results else None

    async def get_by_email(self, db, email):
        results = await self._filter_by(email=email)
        return results[0] if results else None


def _make_tenant(user_id=None):
    return SimpleNamespace(id=uuid4(), user_id=user_id)


def _make_service(tenants=None, users=None) -> TenantService:
    if tenants is None:
        tenants_repo = MockTenantRepo({})
    elif isinstance(tenants, dict):
        tenants_repo = MockTenantRepo(tenants)
    else:
        tenants_repo = tenants

    if users is None:
        users_repo = MockReadOnlyRepo({})
    elif isinstance(users, dict):
        users_repo = MockReadOnlyRepo(users)
    else:
        users_repo = users
    return TenantService(
        tenant_repo=tenants_repo,
        user_repo=users_repo,
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

        svc = _make_service(tenants=FailingRepo({tenant.id: tenant}), users=MockReadOnlyRepo({user.id: user}))

        with pytest.raises(TenantAlreadyLinkedError):
            await svc.link_user(mock_db, tenant.id, user.id, current_user=_make_admin())

        assert mock_db.rollback.called

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())

        class FailingRepo(MockTenantRepo):
            async def update(self, db, id, payload):
                raise IntegrityError("UPDATE", {}, Exception("some unrelated constraint violation"))

        svc = _make_service(
            tenants=FailingRepo({tenant.id: tenant}),
            users=MockReadOnlyRepo({user.id: user}),
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
        svc = _make_service(tenants=repo)
        admin = _make_admin()

        result = await svc.get_tenant(mock_db, tenant.id, current_user=admin)
        assert result is tenant

    async def test_manager_can_access_unclaimed_tenant(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant})
        svc = _make_service(tenants=repo)
        manager = _make_manager()

        result = await svc.get_tenant(mock_db, tenant.id, current_user=manager)
        assert result is tenant

    async def test_manager_can_access_own_tenant(self, mock_db):
        tenant = _make_tenant()
        manager = _make_manager()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {manager.id}})
        svc = _make_service(tenants=repo)

        result = await svc.get_tenant(mock_db, tenant.id, current_user=manager)
        assert result is tenant

    async def test_manager_cannot_access_another_managers_tenant(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = _make_service(tenants=repo)
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.get_tenant(mock_db, tenant.id, current_user=manager)

    async def test_update_tenant_enforces_authorization(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = _make_service(tenants=repo)
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.update_tenant(mock_db, tenant.id, payload={}, current_user=manager)

    async def test_delete_tenant_enforces_authorization(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = _make_service(tenants=repo)
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
        svc = _make_service(tenants=repo)

        result = await svc.list_tenants(mock_db, current_user=manager)
        assert result.items == [owned]
        assert result.total == 1

    async def test_list_tenants_admin_sees_everything(self, mock_db):
        t1, t2 = _make_tenant(), _make_tenant()
        repo = MockCRUDRepo({t1.id: t1, t2.id: t2})
        svc = _make_service(tenants=repo)
        admin = _make_admin()

        result = await svc.list_tenants(mock_db, current_user=admin)
        assert result.items == [t1, t2]
        assert result.total == 2

    async def test_link_user_enforces_authorization(self, mock_db):
        tenant = _make_tenant()
        user = SimpleNamespace(id=uuid4())
        repo = MockOwnershipTenantRepo({tenant.id: tenant}, owners={tenant.id: {uuid4()}})
        svc = _make_service(tenants=repo, users=MockReadOnlyRepo({user.id: user}))
        manager = _make_manager()

        with pytest.raises(TenantForbiddenError):
            await svc.link_user(mock_db, tenant.id, user.id, current_user=manager)


# ─── create_tenant ───────────────────────────────────────────────────────────


def _make_regular_user():
    return SimpleNamespace(id=uuid4(), role=UserRole.USER)


@pytest.mark.asyncio
class TestCreateTenant:
    async def test_admin_can_create_tenant(self, mock_db):

        svc = _make_service()
        payload = make_tenant()

        result = await svc.create_tenant(mock_db, payload=payload, current_user=_make_admin())

        assert result is not None

    async def test_manager_can_create_tenant(self, mock_db):
        svc = _make_service()
        payload = make_tenant()

        result = await svc.create_tenant(mock_db, payload=payload, current_user=_make_manager())

        assert result is not None

    async def test_user_role_is_forbidden(self, mock_db):
        """A brand-new tenant has no owner to check ownership against —
        this is the one place role alone (not resource ownership) is the
        whole check, and it must not be skippable."""

        repo = MockTenantRepo()
        svc = _make_service(tenants=repo)
        payload = make_tenant()

        with pytest.raises(TenantForbiddenError):
            await svc.create_tenant(mock_db, payload=payload, current_user=_make_regular_user())

        assert repo.created_payloads == []

    async def test_current_user_is_required(self, mock_db):

        svc = _make_service()
        payload = make_tenant()

        with pytest.raises(TypeError):
            await svc.create_tenant(mock_db, payload=payload)

    async def test_raises_when_email_already_exists(self, mock_db):
        existing = SimpleNamespace(id=uuid4(), email="taken@example.com")
        repo = MockTenantRepo({existing.id: existing})
        svc = _make_service(tenants=repo)
        payload = make_tenant(email="taken@example.com")

        with pytest.raises(TenantAlreadyExistsError):
            await svc.create_tenant(mock_db, payload=payload, current_user=_make_admin())

        assert repo.created_payloads == []

    async def test_translates_integrity_error_to_email_conflict(self, mock_db):
        """Simulates a race where the pre-check passes but a concurrent
        create win first, mirroring UserService's equivalent test."""

        class FailingCreateRepo(MockTenantRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT", {}, Exception('duplicate key value violates unique constraint "ix_tenants_email"')
                )

        svc = _make_service(tenants=FailingCreateRepo())
        payload = make_tenant(email="race@example.com")

        with pytest.raises(TenantAlreadyExistsError):
            await svc.create_tenant(mock_db, payload=payload, current_user=_make_admin())


@pytest.mark.asyncio
class TestUpdateTenantEmailUniqueness:
    async def test_raises_when_email_already_exists(self, mock_db):
        target = _make_tenant()
        other = SimpleNamespace(id=uuid4(), user_id=None, email="taken@example.com")
        repo = MockTenantRepo({target.id: target, other.id: other})
        svc = _make_service(tenants=repo)

        with pytest.raises(TenantAlreadyExistsError):
            await svc.update_tenant(
                mock_db,
                target.id,
                payload={"email": "taken@example.com"},
                current_user=_make_admin(),
            )

    async def test_updating_own_email_to_same_value_is_allowed(self, mock_db):
        target = SimpleNamespace(id=uuid4(), user_id=None, email="mine@example.com")
        repo = MockTenantRepo({target.id: target})
        svc = _make_service(tenants=repo)

        result = await svc.update_tenant(
            mock_db, target.id, payload={"email": "mine@example.com"}, current_user=_make_admin()
        )

        assert result is not None


# ─── _authorize_user_to_tenant fails closed for unclaimed tenants ───────────


@pytest.mark.asyncio
class TestAuthorizeUserToTenantFailsClosed:
    async def test_user_role_is_forbidden_for_unclaimed_tenant(self, mock_db):
        """Regression test: MockOwnershipTenantRepo.is_accessible_by_manager
        (mirroring the real repo's EXISTS clause) returns True for *any*
        id when a tenant is unclaimed — it never checks role. Before the
        fail-closed fix, a plain USER role reached that query and was
        incorrectly authorized. It must now be rejected before the query
        ever runs."""
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant})  # unclaimed
        svc = _make_service(tenants=repo)
        user = _make_regular_user()

        with pytest.raises(TenantForbiddenError):
            await svc.get_tenant(mock_db, tenant.id, current_user=user)

    async def test_unrecognized_role_is_forbidden_for_unclaimed_tenant(self, mock_db):
        tenant = _make_tenant()
        repo = MockOwnershipTenantRepo({tenant.id: tenant})  # unclaimed
        svc = _make_service(tenants=repo)
        stub = SimpleNamespace(id=uuid4(), role=None)

        with pytest.raises(TenantForbiddenError):
            await svc.get_tenant(mock_db, tenant.id, current_user=stub)
