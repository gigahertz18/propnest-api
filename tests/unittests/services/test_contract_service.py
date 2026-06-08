from types import SimpleNamespace
import pytest
from sqlalchemy.exc import IntegrityError

from app.services.contract_service import ContractService
from app.services.exceptions import ContractActiveError


def test_create_contract_translates_integrity_error_with_uq():
    class Repo:
        def create(self, db, payload):
            raise IntegrityError("INSERT", {}, Exception('pq: duplicate key value violates unique constraint "uq_active_contract_property"'))

    svc = ContractService(contract_repo=Repo())

    with pytest.raises(ContractActiveError):
        svc.create_contract(db=None, payload=None)


def test_create_contract_translates_integrity_error_with_property_key():
    class Repo:
        def create(self, db, payload):
            raise IntegrityError("INSERT", {}, Exception('duplicate key value violates unique constraint "whatever" for property_id'))

    svc = ContractService(contract_repo=Repo())

    with pytest.raises(ContractActiveError):
        svc.create_contract(db=None, payload=None)


def test_create_contract_reraises_other_integrity_errors():
    class Repo:
        def create(self, db, payload):
            raise IntegrityError("INSERT", {}, Exception('some other integrity problem'))

    svc = ContractService(contract_repo=Repo())

    with pytest.raises(IntegrityError):
        svc.create_contract(db=None, payload=None)


def test_contract_service_delegates_to_repo_methods():
    class Repo:
        def __init__(self):
            self.calls = []

        def get_all(self, db, skip=0, limit=100):
            return ["a"]

        def get_by_id(self, db, id):
            return "byid"

        def create(self, db, payload):
            return "created"

        def update(self, db, id, payload):
            return "updated"

        def delete(self, db, id):
            return "deleted"

        def get_by_property(self, db, property_id):
            return ["p"]

        def get_active_contract_by_property(self, db, property_id):
            return "active"

        def get_by_tenant(self, db, tenant_id):
            return ["t"]

        def get_by_status(self, db, status):
            return ["s"]

        def get_by_rental_type(self, db, rental_type):
            return ["r"]

        def get_by_booking_source(self, db, booking_source):
            return ["b"]

    repo = Repo()
    svc = ContractService(contract_repo=repo)

    assert svc.list_contracts(db=None) == ["a"]
    assert svc.get_contract(db=None, id=1) == "byid"
    assert svc.create_contract(db=None, payload=None) == "created"
    assert svc.update_contract(db=None, id=1, payload=None) == "updated"
    assert svc.delete_contract(db=None, id=1) == "deleted"
    assert svc.get_by_property(db=None, property_id=1) == ["p"]
    assert svc.get_active_contract_by_property(db=None, property_id=1) == "active"
    assert svc.get_by_tenant(db=None, tenant_id=1) == ["t"]
    assert svc.get_by_status(db=None, status="s") == ["s"]
    assert svc.get_by_rental_type(db=None, rental_type="r") == ["r"]
    assert svc.get_by_booking_source(db=None, booking_source="b") == ["b"]
