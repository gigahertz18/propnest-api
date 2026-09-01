import pytest

from uuid import uuid4
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.core.models.audit_log import AuditAction, AuditLog
from app.models.property import PropertyStatus
from app.identity.models.user import UserRole
from app.services.property_service import PropertyService
from app.core.services.exceptions import (
    RelatedResourceNotFoundError,
    PropertyAlreadyExistsError,
    PropertyForbiddenError,
    UserNotFoundError,
    PropertyManagerAssignmentError,
)
from app.schemas.property import PropertyCreate, PropertyUpdate
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo


class MockPropertyRepo(MockCRUDRepo):
    async def get_by_status(self, db, status):
        return await self._filter_by(status=status)

    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return await self._filter_by(manager_id=manager_id)


def _make_service(properties=None, users=None) -> PropertyService:
    if properties is None:
        property_repo = MockPropertyRepo({})
    elif isinstance(properties, dict):
        property_repo = MockPropertyRepo(properties)
    else:
        property_repo = properties

    if users is None:
        user_repo = None
    elif isinstance(users, dict):
        user_repo = MockReadOnlyRepo(users)
    else:
        user_repo = users

    return PropertyService(
        property_repo=property_repo,
        user_repo=user_repo,
    )


def _admin() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)


@pytest.mark.asyncio
class TestListProperties:
    async def test_returns_all_properties(self, mock_db):
        prop = SimpleNamespace(id=uuid4())
        svc = _make_service(properties={prop.id: prop})
        result = await svc.list_properties(mock_db, current_user=_admin())
        assert result.items == [prop]
        assert result.total == 1

    async def test_returns_empty_list_when_none_exist(self, mock_db):
        svc = _make_service()
        result = await svc.list_properties(mock_db, current_user=_admin())
        assert result.items == []
        assert result.total == 0

    async def test_admin_sees_all_properties(self, mock_db):
        admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)
        owned_prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        other_prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(properties={owned_prop.id: owned_prop, other_prop.id: other_prop})

        result = await svc.list_properties(mock_db, current_user=admin)

        assert result.items == [owned_prop, other_prop]
        assert result.total == 2

    async def test_current_user_is_required(self, mock_db):
        """current_user has no default — a caller that forgets to pass it
        gets a loud TypeError, not a silent bypass. This is the specific
        fix for the regression where Tenant/Document/Property
        authorization was silently skippable when current_user was
        omitted."""
        prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(TypeError):
            await svc.list_properties(mock_db)

    async def test_manager_only_sees_own_properties(self, mock_db):
        manager_id = uuid4()
        manager = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)
        owned = SimpleNamespace(id=uuid4(), manager_id=manager_id)
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(properties={owned.id: owned, other.id: other})

        result = await svc.list_properties(mock_db, current_user=manager)

        assert result.items == [owned]
        assert result.total == 1


@pytest.mark.asyncio
class TestGetProperty:
    async def test_returns_property_when_found(self, mock_db):
        prop = SimpleNamespace(id=uuid4())
        svc = _make_service(properties={prop.id: prop})
        assert await svc.get_property(mock_db, prop.id, current_user=_admin()) is prop

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_property(mock_db, uuid4(), current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(properties={prop.id: prop})
        with pytest.raises(TypeError):
            await svc.get_property(mock_db, prop.id)

    async def test_admin_bypasses_ownership_check(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)
        svc = _make_service(properties={prop.id: prop})

        assert await svc.get_property(mock_db, prop.id, current_user=admin) is prop

    async def test_manager_can_get_own_property(self, mock_db):
        manager_id = uuid4()
        prop = SimpleNamespace(id=uuid4(), manager_id=manager_id)
        manager = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)
        svc = _make_service(properties={prop.id: prop})

        assert await svc.get_property(mock_db, prop.id, current_user=manager) is prop

    async def test_manager_cannot_get_another_managers_property(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        manager = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)
        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(PropertyForbiddenError):
            await svc.get_property(mock_db, prop.id, current_user=manager)

    async def test_user_role_is_forbidden(self, mock_db):
        """Regression test: get_property's ownership check only ever
        special-cased MANAGER (`if role == MANAGER and id != manager_id:
        raise`), so a plain USER role fell through the condition
        entirely and was treated as authorized, identical to an admin.
        Must be rejected before ownership is even considered — matching
        the fail-closed pattern used everywhere else in the service
        layer (_authorize_user_to_property, _list_scoped_by_manager,
        _authorize_user_to_tenant)."""
        prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        user = SimpleNamespace(id=uuid4(), role=UserRole.USER)
        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(PropertyForbiddenError):
            await svc.get_property(mock_db, prop.id, current_user=user)

    async def test_unrecognized_role_is_forbidden(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        stub = SimpleNamespace(id=uuid4(), role=None)
        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(PropertyForbiddenError):
            await svc.get_property(mock_db, prop.id, current_user=stub)


@pytest.mark.asyncio
class TestCreateProperty:
    async def test_creates_and_commits(self, mock_db):
        svc = _make_service()
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        admin = _admin()
        created = await svc.create_property(mock_db, payload, current_user=admin)

        assert created.name == "Unit A"
        assert created.address == "123 Main St"
        assert mock_db.commit.called

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == admin.id
        assert row.action == AuditAction.CREATE
        assert row.entity_type == "Property"
        assert row.entity_id == created.id

    async def test_translates_duplicate_name_and_address(self, mock_db):
        class FailingRepo(MockPropertyRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT",
                    {},
                    Exception('duplicate key value violates unique constraint "uq_property_name_address"'),
                )

        svc = _make_service(properties=FailingRepo())
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        with pytest.raises(PropertyAlreadyExistsError):
            await svc.create_property(mock_db, payload, current_user=_admin())

        # Regression: the repo write failed before write_audit_log ran, so
        # no audit row was ever added to the session — nothing to orphan.
        assert not mock_db.add.called
        assert not mock_db.commit.called

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        class FailingRepo(MockPropertyRepo):
            async def create(self, db, payload):
                raise IntegrityError("INSERT", {}, Exception("some unrelated constraint violation"))

        svc = _make_service(properties=FailingRepo())
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        with pytest.raises(IntegrityError):
            await svc.create_property(mock_db, payload, current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        svc = _make_service()
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        with pytest.raises(TypeError):
            await svc.create_property(mock_db, payload)

    async def test_manager_is_forbidden(self, mock_db):
        svc = _make_service()
        payload = PropertyCreate(name="Unit A", address="123 Main St")
        manager = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(PropertyForbiddenError):
            await svc.create_property(mock_db, payload, current_user=manager)

    async def test_user_role_is_forbidden(self, mock_db):
        svc = _make_service()
        payload = PropertyCreate(name="Unit A", address="123 Main St")
        user = SimpleNamespace(id=uuid4(), role=UserRole.USER)

        with pytest.raises(PropertyForbiddenError):
            await svc.create_property(mock_db, payload, current_user=user)


@pytest.mark.asyncio
class TestUpdateProperty:
    async def test_updates_existing_property(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), name="Old Name", address="Old Address")
        svc = _make_service(properties={prop.id: prop})
        payload = PropertyUpdate(name="New Name")

        admin = _admin()
        updated = await svc.update_property(mock_db, prop.id, payload, current_user=admin)

        assert updated.name == "New Name"
        assert mock_db.commit.called

        row = mock_db.add.call_args.args[0]
        assert row.action == AuditAction.UPDATE
        assert row.entity_type == "Property"
        assert row.entity_id == prop.id
        assert row.actor_id == admin.id

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.update_property(mock_db, uuid4(), PropertyUpdate(name="New Name"), current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        prop = SimpleNamespace(id=uuid4())
        svc = _make_service(properties={prop.id: prop})
        with pytest.raises(TypeError):
            await svc.update_property(mock_db, prop.id, PropertyUpdate(name="New Name"))

    async def test_returns_none_when_repo_update_returns_none(self, mock_db):
        """Edge case: property existed at get_property time but the repo's
        update returns None anyway (e.g. deleted concurrently). The service
        doesn't paper over this — it returns None and lets the route 404."""
        prop = SimpleNamespace(id=uuid4())

        class Repo(MockPropertyRepo):
            async def update(self, db, id, payload):
                return None

        svc = _make_service(properties=Repo({prop.id: prop}))

        result = await svc.update_property(mock_db, prop.id, PropertyUpdate(name="New Name"), current_user=_admin())

        assert result is None

    async def test_translates_duplicate_name_and_address(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        class FailingRepo(MockPropertyRepo):
            async def update(self, db, id, payload):
                raise IntegrityError(
                    "UPDATE",
                    {},
                    Exception('duplicate key value violates unique constraint "uq_property_name_address"'),
                )

        # svc = PropertyService(property_repo=FailingRepo({prop.id: prop}))
        svc = _make_service(properties=FailingRepo({prop.id: prop}))

        with pytest.raises(PropertyAlreadyExistsError):
            await svc.update_property(
                mock_db, prop.id, PropertyUpdate(name="Unit A", address="123 Main St"), current_user=_admin()
            )

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        class FailingRepo(MockPropertyRepo):
            async def update(self, db, id, payload):
                raise IntegrityError("UPDATE", {}, Exception("some unrelated constraint violation"))

        svc = _make_service(properties=FailingRepo({prop.id: prop}))

        with pytest.raises(IntegrityError):
            await svc.update_property(mock_db, prop.id, PropertyUpdate(name="Unit A"), current_user=_admin())


@pytest.mark.asyncio
class TestDeleteProperty:
    async def test_deletes_existing_property(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        svc = _make_service(properties={prop.id: prop})

        admin = _admin()
        deleted = await svc.delete_property(mock_db, prop.id, current_user=admin)

        assert deleted is prop
        assert mock_db.commit.called

        row = mock_db.add.call_args.args[0]
        assert row.action == AuditAction.DELETE
        assert row.entity_type == "Property"
        assert row.entity_id == prop.id

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.delete_property(mock_db, uuid4(), current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        svc = _make_service(properties={prop.id: prop})
        with pytest.raises(TypeError):
            await svc.delete_property(mock_db, prop.id)

    async def test_returns_none_when_repo_delete_returns_none(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        class Repo(MockPropertyRepo):
            async def delete(self, db, id):
                return None

        svc = _make_service(properties=Repo({prop.id: prop}))

        result = await svc.delete_property(mock_db, prop.id, current_user=_admin())

        assert result is None


@pytest.mark.asyncio
class TestGetByStatus:
    async def test_delegates_to_repo(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), status=PropertyStatus.vacant)
        svc = _make_service(properties={prop.id: prop})
        assert await svc.get_by_status(mock_db, PropertyStatus.vacant) == [prop]

    async def test_returns_empty_list_when_none_match(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), status=PropertyStatus.occupied)
        svc = _make_service(properties={prop.id: prop})
        assert await svc.get_by_status(mock_db, PropertyStatus.vacant) == []


@pytest.mark.asyncio
class TestAssignManager:
    async def test_assigns_manager_successfully(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=None)
        manager_id = uuid4()
        manager_user = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)

        svc = _make_service(
            properties={prop.id: prop},
            users={manager_id: manager_user},
        )

        updated = await svc.assign_manager(mock_db, prop.id, manager_id, current_user=_admin())

        assert updated.manager_id == manager_id
        assert mock_db.commit.called

    async def test_reassigns_overwriting_previous_manager(self, mock_db):
        old_manager_id = uuid4()
        new_manager_id = uuid4()
        prop = SimpleNamespace(id=uuid4(), manager_id=old_manager_id)
        new_manager_user = SimpleNamespace(id=new_manager_id, role=UserRole.MANAGER)

        svc = _make_service(
            properties={prop.id: prop},
            users={new_manager_id: new_manager_user},
        )

        updated = await svc.assign_manager(mock_db, prop.id, new_manager_id, current_user=_admin())

        assert updated.manager_id == new_manager_id

    async def test_raises_when_property_not_found(self, mock_db):

        manager_id = uuid4()
        svc = _make_service(users={manager_id: SimpleNamespace(id=manager_id, role=UserRole.MANAGER)})
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.assign_manager(mock_db, uuid4(), manager_id, current_user=_admin())

    async def test_raises_when_manager_user_not_found(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=None)
        svc = _make_service(properties={prop.id: prop}, users={})

        with pytest.raises(UserNotFoundError):
            await svc.assign_manager(mock_db, prop.id, uuid4(), current_user=_admin())

    async def test_raises_when_assignee_is_not_a_manager(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=None)
        regular_user_id = uuid4()
        regular_user = SimpleNamespace(id=regular_user_id, role=UserRole.USER)

        svc = _make_service(
            properties={prop.id: prop},
            users={regular_user_id: regular_user},
        )
        with pytest.raises(PropertyManagerAssignmentError):
            await svc.assign_manager(mock_db, prop.id, regular_user_id, current_user=_admin())

    async def test_raises_when_assignee_is_an_admin(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=None)
        admin_id = uuid4()
        admin_user = SimpleNamespace(id=admin_id, role=UserRole.ADMIN)

        svc = _make_service(
            properties={prop.id: prop},
            users={admin_id: admin_user},
        )

        with pytest.raises(PropertyManagerAssignmentError):
            await svc.assign_manager(mock_db, prop.id, admin_id, current_user=_admin())

    async def test_current_user_is_required(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=None)
        manager_id = uuid4()

        svc = _make_service(
            properties={prop.id: prop},
            users={manager_id: SimpleNamespace(id=manager_id, role=UserRole.MANAGER)},
        )
        with pytest.raises(TypeError):
            await svc.assign_manager(mock_db, prop.id, manager_id)

    async def test_manager_cannot_assign_manager_even_on_owned_property(self, mock_db):
        """Regression test: assign_manager previously had no explicit
        role check of its own — it relied on get_property's ownership
        check, which a manager who owns the property would pass. Only
        admins may reassign a property's manager."""
        manager_id = uuid4()
        prop = SimpleNamespace(id=uuid4(), manager_id=manager_id)
        new_manager_id = uuid4()

        svc = _make_service(
            properties={prop.id: prop},
            users={new_manager_id: SimpleNamespace(id=new_manager_id, role=UserRole.MANAGER)},
        )

        with pytest.raises(PropertyForbiddenError):
            await svc.assign_manager(
                mock_db, prop.id, new_manager_id, current_user=SimpleNamespace(id=manager_id, role=UserRole.MANAGER)
            )

    async def test_raises_runtime_error_when_user_repo_not_injected(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), manager_id=None)

        svc = _make_service(properties={prop.id: prop})

        with pytest.raises(RuntimeError):
            await svc.assign_manager(mock_db, prop.id, uuid4(), current_user=_admin())
