import pytest
from sqlalchemy.exc import IntegrityError

from app.services.contract_service import ContractService
from app.services.exceptions import ContractActiveError

@pytest.mark.asyncio
async def test_create_contract_translates_integrity_error_with_uq(mock_db):
    class Repo:
        async def create(self, db, payload):
            raise IntegrityError(
                "INSERT",
                {},
                Exception('pq: duplicate key value violates unique constraint "uq_active_contract_property"'),
            )

    svc = ContractService(contract_repo=Repo())

    with pytest.raises(ContractActiveError):
        await svc.create_contract(db=mock_db, payload=None)

@pytest.mark.asyncio
async def test_create_contract_translates_integrity_error_with_property_key(mock_db):
    class Repo:
        async def create(self, db, payload):
            raise IntegrityError(
                "INSERT", {}, Exception('duplicate key value violates unique constraint "whatever" for property_id')
            )

    svc = ContractService(contract_repo=Repo())

    with pytest.raises(ContractActiveError):
        await svc.create_contract(db=mock_db, payload=None)

@pytest.mark.asyncio
async def test_create_contract_reraises_other_integrity_errors(mock_db):
    class Repo:
        async def create(self, db, payload):
            raise IntegrityError("INSERT", {}, Exception("some other integrity problem"))

    svc = ContractService(contract_repo=Repo())

    with pytest.raises(IntegrityError):
        await svc.create_contract(db=mock_db, payload=None)

@pytest.mark.asyncio
async def test_contract_service_delegates_to_repo_methods(mock_db):
    class Repo:
        def __init__(self):
            self.calls = []

        async def get_all(self, db, skip=0, limit=100):
            return ["a"]

        async def get_by_id(self, db, id):
            return "byid"

        async def create(self, db, payload):
            return "created"

        async def update(self, db, id, payload):
            return "updated"

        async def delete(self, db, id):
            return "deleted"

        async def get_by_property(self, db, property_id):
            return ["p"]

        async def get_active_contract_by_property(self, db, property_id):
            return "active"

        async def get_by_tenant(self, db, tenant_id):
            return ["t"]

        async def get_by_status(self, db, status):
            return ["s"]

        async def get_by_rental_type(self, db, rental_type):
            return ["r"]

        async def get_by_booking_source(self, db, booking_source):
            return ["b"]

    repo = Repo()
    svc = ContractService(contract_repo=repo)

    assert await svc.list_contracts(db=mock_db) == ["a"]
    assert await svc.get_contract(db=mock_db, id=1) == "byid"
    assert await svc.create_contract(db=mock_db, payload=None) == "created"
    assert await svc.update_contract(db=mock_db, id=1, payload=None) == "updated"
    assert await svc.delete_contract(db=mock_db, id=1) == "deleted"
    assert await svc.get_by_property(db=mock_db, property_id=1) == ["p"]
    assert await svc.get_active_contract_by_property(db=mock_db, property_id=1) == "active"
    assert await svc.get_active_contract_by_property(db=mock_db, property_id=1) == "active"
    assert await svc.get_by_tenant(db=mock_db, tenant_id=1) == ["t"]
    assert await svc.get_by_status(db=mock_db, status="s") == ["s"]
    assert await svc.get_by_rental_type(db=mock_db, rental_type="r") == ["r"]
    assert await svc.get_by_booking_source(db=mock_db, booking_source="b") == ["b"]
