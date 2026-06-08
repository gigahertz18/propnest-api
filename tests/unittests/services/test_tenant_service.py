from types import SimpleNamespace

from app.services.tenant_service import TenantService


def test_tenant_service_delegates_to_repo_methods():
    class Repo:
        def get_all(self, db, skip=0, limit=100):
            return ["t1"]

        def get_by_id(self, db, id):
            return "byid"

        def create(self, db, payload):
            return "created"

        def update(self, db, id, payload):
            return "updated"

        def delete(self, db, id):
            return "deleted"

        def get_by_email(self, db, email):
            return "email"

        def get_by_phone_number(self, db, phone_number):
            return "phone"

        def get_by_full_name(self, db, full_name):
            return ["name"]

        def get_by_occupation(self, db, occupation):
            return ["occ"]

        def get_by_date_of_birth(self, db, dob):
            return ["dob"]

    repo = Repo()
    svc = TenantService(tenant_repo=repo)

    assert svc.list_tenants(db=None) == ["t1"]
    assert svc.get_tenant(db=None, id=1) == "byid"
    assert svc.create_tenant(db=None, payload=None) == "created"
    assert svc.update_tenant(db=None, id=1, payload=None) == "updated"
    assert svc.delete_tenant(db=None, id=1) == "deleted"
    assert svc.get_by_email(db=None, email="e") == "email"
    assert svc.get_by_phone_number(db=None, phone_number="p") == "phone"
    assert svc.get_by_full_name(db=None, full_name="n") == ["name"]
    assert svc.get_by_occupation(db=None, occupation="o") == ["occ"]
    from datetime import date

    assert svc.get_by_date_of_birth(db=None, date_of_birth=date(2000, 1, 1)) == ["dob"]
