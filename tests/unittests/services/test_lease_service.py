import pytest

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.models.audit_log import AuditAction, AuditLog
from app.models.contract import RentalType
from app.repositories.lease import lease_repo
from app.schemas.lease import LeaseCreate, LeaseUpdate
from app.services.lease_service import LeaseService
from app.core.services.exceptions import (
    LeaseAlreadyExistsError,
    LeaseForbiddenError,
    LeaseRentalTypeError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager, make_regular_user


class MockLeaseRepo(MockCRUDRepo):
    async def get_by_contract(self, db, contract_id):
        matches = await self._filter_by(contract_id=contract_id)
        return matches[0] if matches else None


class MockLeaseRepoWithScoping(MockLeaseRepo):
    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return [ls for ls in self.records.values() if getattr(ls, "manager_id", None) == manager_id]


def _make_service(leases=None, contracts=None, properties=None) -> LeaseService:
    if leases is None:
        lease_repo_ = MockLeaseRepo({})
    elif isinstance(leases, dict):
        lease_repo_ = MockLeaseRepo(leases)
    else:
        lease_repo_ = leases

    if contracts is None:
        contract_repo = MockReadOnlyRepo({})
    elif isinstance(contracts, dict):
        contract_repo = MockReadOnlyRepo(contracts)
    else:
        contract_repo = contracts

    if properties is None:
        property_repo = MockReadOnlyRepo({})
    elif isinstance(properties, dict):
        property_repo = MockReadOnlyRepo(properties)
    else:
        property_repo = properties

    return LeaseService(lease_repo=lease_repo_, contract_repo=contract_repo, property_repo=property_repo)


def _payload(**kwargs):
    defaults = dict(
        contract_id=uuid4(),
        monthly_rent=Decimal("15000.00"),
        due_day=5,
        billing_cycle="monthly",
        security_deposit=Decimal("15000.00"),
        advance_payment=None,
        late_fee_amount=Decimal("500.00"),
        late_fee_percent=None,
        grace_period_days=3,
        renewal_option="none",
        status="ACTIVE",
        start_date=date(2026, 1, 1),
        end_date=None,
    )
    defaults.update(kwargs)
    return LeaseCreate(**defaults)


# ─── Construction / class attributes ───────────────────────────────────────


class TestLeaseServiceClassAttributes:
    def test_forbidden_error_is_lease_forbidden_error(self):
        assert LeaseService.forbidden_error is LeaseForbiddenError

    def test_lease_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(LeaseForbiddenError, ResourceForbiddenError)

    def test_contract_repo_and_property_repo_default_to_none(self):
        svc = LeaseService(lease_repo=lease_repo)
        assert svc.contract_repo is None
        assert svc.property_repo is None


# ─── get_lease ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetLease:
    async def test_returns_lease_when_found(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        assert await svc.get_lease(mock_db, lease_id, current_user=make_admin()) is lease

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_lease(mock_db, uuid4(), current_user=make_admin())

    async def test_current_user_is_required(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(TypeError):
            await svc.get_lease(mock_db, lease_id)

    async def test_manager_can_get_lease_on_owned_property(self, mock_db):
        manager_id, lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        assert await svc.get_lease(mock_db, lease_id, current_user=make_manager(manager_id)) is lease

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(LeaseForbiddenError):
            await svc.get_lease(mock_db, lease_id, current_user=make_manager())

    async def test_user_role_is_forbidden(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(LeaseForbiddenError):
            await svc.get_lease(mock_db, lease_id, current_user=make_regular_user())


# ─── get_by_contract ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetByContract:
    async def test_returns_lease_for_contract(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        lease = SimpleNamespace(id=uuid4(), contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease.id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        assert await svc.get_by_contract(mock_db, contract_id, current_user=make_admin()) is lease

    async def test_returns_none_when_no_lease_for_contract(self, mock_db):
        svc = _make_service()
        assert await svc.get_by_contract(mock_db, uuid4(), current_user=make_admin()) is None


# ─── create_lease ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateLease:
    async def test_admin_can_create_for_long_term_contract(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.create_lease(mock_db, _payload(contract_id=contract_id), current_user=admin)

        assert result.contract_id == contract_id
        assert mock_db.commit.called

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == admin.id
        assert row.action == AuditAction.CREATE
        assert row.entity_type == "Lease"
        assert row.entity_id == result.id

    async def test_manager_can_create_for_owned_property(self, mock_db):
        manager_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        result = await svc.create_lease(
            mock_db, _payload(contract_id=contract_id), current_user=make_manager(manager_id)
        )

        assert result.contract_id == contract_id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.lease_repo

        with pytest.raises(LeaseForbiddenError):
            await svc.create_lease(mock_db, _payload(contract_id=contract_id), current_user=make_manager())

        assert repo.created_payloads == []
        assert not mock_db.commit.called

    async def test_raises_when_contract_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_lease(mock_db, _payload(contract_id=uuid4()), current_user=make_admin())

    async def test_rejects_short_term_contract(self, mock_db):
        """Core PRD guard: Lease is long-term-specific."""
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.short_term)
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.lease_repo

        with pytest.raises(LeaseRentalTypeError):
            await svc.create_lease(mock_db, _payload(contract_id=contract_id), current_user=make_admin())

        assert repo.created_payloads == []

    async def test_current_user_is_required(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(TypeError):
            await svc.create_lease(mock_db, _payload(contract_id=contract_id))

    async def test_user_role_is_forbidden(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(LeaseForbiddenError):
            await svc.create_lease(mock_db, _payload(contract_id=contract_id), current_user=make_regular_user())

    async def test_translates_integrity_error_with_uq_constraint_name(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)

        class Repo(MockLeaseRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT", {}, Exception('duplicate key value violates unique constraint "uq_lease_contract_id"')
                )

        svc = LeaseService(
            lease_repo=Repo(),
            contract_repo=MockReadOnlyRepo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
        )

        with pytest.raises(LeaseAlreadyExistsError):
            await svc.create_lease(mock_db, _payload(contract_id=contract_id), current_user=make_admin())

        # Regression: the repo write failed before write_audit_log ran, so
        # no audit row was ever added to the session — nothing to orphan.
        assert not mock_db.add.called
        assert not mock_db.commit.called

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        contract_id, prop_id = uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, rental_type=RentalType.long_term)

        class Repo(MockLeaseRepo):
            async def create(self, db, payload):
                raise IntegrityError("INSERT", {}, Exception("some other integrity problem"))

        svc = LeaseService(
            lease_repo=Repo(),
            contract_repo=MockReadOnlyRepo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
        )

        with pytest.raises(IntegrityError):
            await svc.create_lease(mock_db, _payload(contract_id=contract_id), current_user=make_admin())


# ─── update_lease ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateLease:
    async def test_raises_when_lease_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.update_lease(mock_db, uuid4(), LeaseUpdate(status="ENDED"), current_user=make_admin())

    async def test_admin_can_update_any_lease(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id, status="ACTIVE")
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.update_lease(mock_db, lease_id, LeaseUpdate(status="ENDED"), current_user=admin)

        assert result.status == "ENDED"
        assert mock_db.commit.called

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == admin.id
        assert row.action == AuditAction.UPDATE
        assert row.entity_type == "Lease"
        assert row.entity_id == lease_id

    async def test_manager_forbidden_for_unowned_lease(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id, status="ACTIVE")
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.lease_repo

        with pytest.raises(LeaseForbiddenError):
            await svc.update_lease(mock_db, lease_id, LeaseUpdate(status="ENDED"), current_user=make_manager())

        assert repo.updated_payloads == []
        assert not mock_db.commit.called


# ─── delete_lease ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteLease:
    async def test_raises_when_lease_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.delete_lease(mock_db, uuid4(), current_user=make_admin())

    async def test_admin_can_delete_any_lease(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        admin = make_admin()
        result = await svc.delete_lease(mock_db, lease_id, current_user=admin)

        assert result is lease
        assert mock_db.commit.called

        mock_db.add.assert_called_once()
        row = mock_db.add.call_args.args[0]
        assert isinstance(row, AuditLog)
        assert row.actor_id == admin.id
        assert row.action == AuditAction.DELETE
        assert row.entity_type == "Lease"
        assert row.entity_id == lease_id

    async def test_manager_forbidden_for_unowned_lease(self, mock_db):
        lease_id, contract_id, prop_id = uuid4(), uuid4(), uuid4()
        lease = SimpleNamespace(id=lease_id, contract_id=contract_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(
            leases={lease_id: lease},
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.lease_repo

        with pytest.raises(LeaseForbiddenError):
            await svc.delete_lease(mock_db, lease_id, current_user=make_manager())

        assert repo.deleted_ids == []
        assert not mock_db.commit.called


# ─── list_leases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListLeases:
    async def test_current_user_is_required(self, mock_db):
        svc = _make_service(leases=MockLeaseRepoWithScoping())
        with pytest.raises(TypeError):
            await svc.list_leases(mock_db)

    async def test_admin_sees_all_leases(self, mock_db):
        l1 = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        l2 = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(leases=MockLeaseRepoWithScoping({l1.id: l1, l2.id: l2}))

        result = await svc.list_leases(mock_db, current_user=make_admin())

        assert result.items == [l1, l2]
        assert result.total == 2

    async def test_manager_only_sees_leases_for_own_properties(self, mock_db):
        manager = make_manager()
        owned = SimpleNamespace(id=uuid4(), manager_id=manager.id)
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = _make_service(leases=MockLeaseRepoWithScoping({owned.id: owned, other.id: other}))

        result = await svc.list_leases(mock_db, current_user=manager)

        assert result.items == [owned]
        assert result.total == 1

    async def test_user_role_is_forbidden(self, mock_db):
        svc = _make_service(leases=MockLeaseRepoWithScoping())
        with pytest.raises(LeaseForbiddenError):
            await svc.list_leases(mock_db, current_user=make_regular_user())
