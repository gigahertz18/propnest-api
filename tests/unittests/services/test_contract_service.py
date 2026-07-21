import pytest

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.models.contract import RentalType
from app.repositories.contract import contract_repo
from app.schemas.contract import ContractCreate, ContractUpdate
from app.services.contract_service import ContractService
from app.services.exceptions import (
    ContractActiveError,
    ContractForbiddenError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager


class MockContractRepo(MockCRUDRepo):
    """Adds Contract's own query methods on top of the generic CRUD base —
    these filter by fields specific to Contract, so they can't live in the
    shared base the way create/update/delete do."""

    async def get_by_property(self, db, property_id):
        return await self._filter_by(property_id=property_id)

    async def get_active_contract_by_property(self, db, property_id):
        matches = await self._filter_by(property_id=property_id, status="ACTIVE")
        return matches[0] if matches else None

    async def get_by_tenant(self, db, tenant_id):
        return await self._filter_by(tenant_id=tenant_id)

    async def get_by_status(self, db, status):
        return await self._filter_by(status=status)

    async def get_by_rental_type(self, db, rental_type):
        return await self._filter_by(rental_type=rental_type)

    async def get_by_booking_source(self, db, booking_source):
        return await self._filter_by(booking_source=booking_source)


def _make_service(properties=None, tenants=None, contracts=None):
    return ContractService(
        contract_repo=MockContractRepo(contracts),
        property_repo=MockReadOnlyRepo(properties),
        tenant_repo=MockReadOnlyRepo(tenants),
    )


def _payload(**kwargs):
    defaults = dict(
        property_id=uuid4(),
        tenant_id=uuid4(),
        rental_type=RentalType.long_term,
        start_date=date(2026, 1, 1),
        end_date=None,
        rent_amount=Decimal("15000.00"),
        deposit=Decimal("15000.00"),
        booking_source="direct",
        status="ACTIVE",
    )
    defaults.update(kwargs)
    return ContractCreate(**defaults)


# ─── Construction / class attributes ───────────────────────────────────────


class TestContractServiceClassAttributes:
    def test_forbidden_error_is_contract_forbidden_error(self):
        """Regression check for the class-attribute refactor: this must
        stay ContractForbiddenError, not the shared ResourceForbiddenError
        base, or routes catching ContractForbiddenError specifically would
        stop matching."""
        assert ContractService.forbidden_error is ContractForbiddenError

    def test_contract_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(ContractForbiddenError, ResourceForbiddenError)

    def test_property_repo_and_tenant_repo_default_to_none(self):
        """Only contract_repo is required; property_repo/tenant_repo are
        optional at construction, matching DocumentService's contract."""
        svc = ContractService(contract_repo=contract_repo)
        assert svc.property_repo is None
        assert svc.tenant_repo is None


# ─── get_contract ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetContract:
    async def test_returns_contract_when_found(self, mock_db):
        contract_id = uuid4()
        contract = SimpleNamespace(id=contract_id)
        svc = _make_service(contracts={contract_id: contract})

        assert await svc.get_contract(mock_db, contract_id) is contract

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_contract(mock_db, uuid4())


# ─── list_contracts ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListContracts:
    async def test_delegates_to_repo(self, mock_db):
        c1, c2 = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
        svc = _make_service(contracts={c1.id: c1, c2.id: c2})

        result = await svc.list_contracts(mock_db)

        assert result.items == [c1, c2]
        assert result.total == 2

    async def test_respects_skip_and_limit(self, mock_db):
        contracts = {uuid4(): SimpleNamespace(id=i) for i in range(5)}
        svc = _make_service(contracts=contracts)

        result = await svc.list_contracts(mock_db, skip=1, limit=2)

        assert len(result.items) == 2
        assert result.total == 5


# ─── create_contract ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateContract:
    async def test_admin_can_create_for_any_property(self, mock_db):
        prop_id, tenant_id = uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.create_contract(
            mock_db, _payload(property_id=prop_id, tenant_id=tenant_id), current_user=make_admin()
        )

        assert result.property_id == prop_id
        assert mock_db.commit.called

    async def test_manager_can_create_for_owned_property(self, mock_db):
        manager_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.create_contract(
            mock_db,
            _payload(property_id=prop_id, tenant_id=tenant_id),
            current_user=make_manager(manager_id),
        )

        assert result.property_id == prop_id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id, tenant_id = uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )
        repo = svc.contract_repo

        with pytest.raises(ContractForbiddenError):
            await svc.create_contract(
                mock_db,
                _payload(property_id=prop_id, tenant_id=tenant_id),
                current_user=make_manager(),  # different manager
            )

        assert repo.created_payloads == []
        assert not mock_db.commit.called

    async def test_raises_when_property_does_not_exist(self, mock_db):
        """Nonexistent property_id -> RelatedResourceNotFoundError before
        any DB write. Routes map this to 404."""
        tenant_id = uuid4()
        svc = _make_service(tenants={tenant_id: SimpleNamespace(id=tenant_id)})
        repo = svc.contract_repo

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_contract(
                mock_db,
                _payload(property_id=uuid4(), tenant_id=tenant_id),
                current_user=make_admin(),
            )

        assert repo.created_payloads == []

    async def test_raises_when_tenant_does_not_exist(self, mock_db):
        """Nonexistent tenant_id -> RelatedResourceNotFoundError before any
        DB write, even though the property does exist."""
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})
        repo = svc.contract_repo

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_contract(
                mock_db,
                _payload(property_id=prop_id, tenant_id=uuid4()),
                current_user=make_admin(),
            )

        assert repo.created_payloads == []

    async def test_property_checked_before_tenant(self, mock_db):
        """When both property_id and tenant_id are missing, the property
        check fails first — matches _validate_related_resources's
        documented check order."""
        svc = _make_service()
        repo = svc.contract_repo

        with pytest.raises(RelatedResourceNotFoundError, match="Property"):
            await svc.create_contract(
                mock_db,
                _payload(property_id=uuid4(), tenant_id=uuid4()),
                current_user=make_admin(),
            )

        assert repo.created_payloads == []

    async def test_skips_authorization_when_no_current_user(self, mock_db):
        """Internal/system callers that don't pass current_user skip
        authorization entirely, but existence validation still runs."""
        prop_id, tenant_id = uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.create_contract(mock_db, _payload(property_id=prop_id, tenant_id=tenant_id))

        assert result.property_id == prop_id

    async def test_translates_integrity_error_with_uq_constraint_name(self, mock_db):
        class Repo(MockContractRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT",
                    {},
                    Exception('duplicate key value violates unique constraint "uq_active_contract_property"'),
                )

        prop_id, tenant_id = uuid4(), uuid4()
        svc = ContractService(
            contract_repo=Repo(),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        with pytest.raises(ContractActiveError):
            await svc.create_contract(
                mock_db, _payload(property_id=prop_id, tenant_id=tenant_id), current_user=make_admin()
            )

    async def test_translates_integrity_error_mentioning_property_id(self, mock_db):
        class Repo(MockContractRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT", {}, Exception('duplicate key value violates unique constraint "whatever" for property_id')
                )

        prop_id, tenant_id = uuid4(), uuid4()
        svc = ContractService(
            contract_repo=Repo(),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        with pytest.raises(ContractActiveError):
            await svc.create_contract(
                mock_db, _payload(property_id=prop_id, tenant_id=tenant_id), current_user=make_admin()
            )

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        class Repo(MockContractRepo):
            async def create(self, db, payload):
                raise IntegrityError("INSERT", {}, Exception("some other integrity problem"))

        prop_id, tenant_id = uuid4(), uuid4()
        svc = ContractService(
            contract_repo=Repo(),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        with pytest.raises(IntegrityError):
            await svc.create_contract(
                mock_db, _payload(property_id=prop_id, tenant_id=tenant_id), current_user=make_admin()
            )


# ─── update_contract ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateContract:
    async def test_raises_when_contract_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.update_contract(mock_db, uuid4(), ContractUpdate(status="INACTIVE"))

    async def test_admin_can_update_any_contract(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.update_contract(
            mock_db, contract_id, ContractUpdate(status="INACTIVE"), current_user=make_admin()
        )

        assert result.status == "INACTIVE"
        assert mock_db.commit.called

    async def test_manager_can_update_owned_contract(self, mock_db):
        manager_id, contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.update_contract(
            mock_db, contract_id, ContractUpdate(status="INACTIVE"), current_user=make_manager(manager_id)
        )

        assert result.status == "INACTIVE"

    async def test_manager_forbidden_for_unowned_contract(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )
        repo = svc.contract_repo

        with pytest.raises(ContractForbiddenError):
            await svc.update_contract(
                mock_db, contract_id, ContractUpdate(status="INACTIVE"), current_user=make_manager()
            )

        assert repo.updated_payloads == []
        assert not mock_db.commit.called

    async def test_skips_authorization_when_no_current_user(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.update_contract(mock_db, contract_id, ContractUpdate(status="INACTIVE"))

        assert result.status == "INACTIVE"

    async def test_returns_none_when_repo_update_returns_none(self, mock_db):
        """Edge case: contract existed at get_contract time but the repo's
        update returns None anyway (e.g. deleted concurrently). The service
        doesn't paper over this — it returns None and lets the route 404."""
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")

        class Repo(MockContractRepo):
            async def update(self, db, id, payload):
                return None

        svc = ContractService(
            contract_repo=Repo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        result = await svc.update_contract(
            mock_db, contract_id, ContractUpdate(status="INACTIVE"), current_user=make_admin()
        )

        assert result is None

    async def test_translates_integrity_error_with_uq_constraint_name(self, mock_db):
        """
        Reactivating a TERMINATED/EXPIRED contract (status -> ACTIVE) can hit the same partial
        unique index create_contract does, since ContractUpdate can change status but not property_id.
        """
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()

        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="TERMINATED")

        class Repo(MockContractRepo):
            async def update(self, db, id, payload):
                raise IntegrityError(
                    "UPDATE",
                    {},
                    Exception('duplicate key value violates unique constraint "uq_active_contract_property"'),
                )

        svc = ContractService(
            contract_repo=Repo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        with pytest.raises(ContractActiveError):
            await svc.update_contract(mock_db, contract_id, ContractUpdate(status="ACTIVE"), current_user=make_admin())

    async def test_translates_integrity_error_mentioning_property_id(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()

        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="TERMINATED")

        class Repo(MockContractRepo):
            async def update(self, db, id, payload):
                raise IntegrityError(
                    "UPDATE",
                    {},
                    Exception('duplicate key value violates unique constraint "whatever" for property_id'),
                )

        svc = ContractService(
            contract_repo=Repo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        with pytest.raises(ContractActiveError):
            await svc.update_contract(mock_db, contract_id, ContractUpdate(status="ACTIVE"), current_user=make_admin())

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")

        class Repo(MockContractRepo):
            async def update(self, db, id, payload):
                raise IntegrityError("UPDATE", {}, Exception("some other integrity problem"))

        svc = ContractService(
            contract_repo=Repo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        with pytest.raises(IntegrityError):
            await svc.update_contract(
                mock_db, contract_id, ContractUpdate(rent_amount=Decimal("2000.00")), current_user=make_admin()
            )


# ─── delete_contract ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteContract:
    async def test_raises_when_contract_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.delete_contract(mock_db, uuid4())

    async def test_admin_can_delete_any_contract(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.delete_contract(mock_db, contract_id, current_user=make_admin())

        assert result is contract
        assert mock_db.commit.called

    async def test_manager_can_delete_owned_contract(self, mock_db):
        manager_id, contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.delete_contract(mock_db, contract_id, current_user=make_manager(manager_id))

        assert result is contract

    async def test_manager_forbidden_for_unowned_contract(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )
        repo = svc.contract_repo

        with pytest.raises(ContractForbiddenError):
            await svc.delete_contract(mock_db, contract_id, current_user=make_manager())

        assert repo.deleted_ids == []
        assert not mock_db.commit.called

    async def test_skips_authorization_when_no_current_user(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")
        svc = _make_service(
            contracts={contract_id: contract},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        result = await svc.delete_contract(mock_db, contract_id)

        assert result is contract

    async def test_returns_none_when_repo_delete_returns_none(self, mock_db):
        contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id, status="ACTIVE")

        class Repo(MockContractRepo):
            async def delete(self, db, id):
                return None

        svc = ContractService(
            contract_repo=Repo({contract_id: contract}),
            property_repo=MockReadOnlyRepo({prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}),
            tenant_repo=MockReadOnlyRepo({tenant_id: SimpleNamespace(id=tenant_id)}),
        )

        result = await svc.delete_contract(mock_db, contract_id, current_user=make_admin())

        assert result is None


# ─── Delegated read-only passthroughs ───────────────────────────────────────


@pytest.mark.asyncio
class TestDelegatedRepoPassthroughs:
    """These methods do no validation/authorization of their own — they're
    thin delegations straight to the repo. One test per method is enough;
    the repo's own behavior is covered by its own test suite."""

    async def test_get_by_property(self, mock_db):
        prop_id = uuid4()
        contract = SimpleNamespace(id=uuid4(), property_id=prop_id)
        svc = _make_service(contracts={contract.id: contract})
        assert await svc.get_by_property(mock_db, prop_id) == [contract]

    async def test_get_active_contract_by_property(self, mock_db):
        prop_id = uuid4()
        contract = SimpleNamespace(id=uuid4(), property_id=prop_id, status="ACTIVE")
        svc = _make_service(contracts={contract.id: contract})
        assert await svc.get_active_contract_by_property(mock_db, prop_id) is contract

    async def test_get_by_tenant(self, mock_db):
        tenant_id = uuid4()
        contract = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
        svc = _make_service(contracts={contract.id: contract})
        assert await svc.get_by_tenant(mock_db, tenant_id) == [contract]

    async def test_get_by_status(self, mock_db):
        contract = SimpleNamespace(id=uuid4(), status="INACTIVE")
        svc = _make_service(contracts={contract.id: contract})
        assert await svc.get_by_status(mock_db, "INACTIVE") == [contract]

    async def test_get_by_rental_type(self, mock_db):
        contract = SimpleNamespace(id=uuid4(), rental_type=RentalType.short_term)
        svc = _make_service(contracts={contract.id: contract})
        assert await svc.get_by_rental_type(mock_db, RentalType.short_term) == [contract]

    async def test_get_by_booking_source(self, mock_db):
        contract = SimpleNamespace(id=uuid4(), booking_source="airbnb")
        svc = _make_service(contracts={contract.id: contract})
        assert await svc.get_by_booking_source(mock_db, "airbnb") == [contract]
