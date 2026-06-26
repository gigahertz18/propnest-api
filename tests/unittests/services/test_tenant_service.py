from datetime import date
from app.services.tenant_service import TenantService


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

        async def get_by_full_name(self, db, full_name):
            return ["name"]

        async def get_by_occupation(self, db, occupation):
            return ["occ"]

        async def get_by_date_of_birth(self, db, dob):
            return ["dob"]

    repo = Repo()
    svc = TenantService(tenant_repo=repo)

    assert await svc.list_tenants(db=mock_db) == ["t1"]
    assert await svc.get_tenant(db=mock_db, id=1) == "byid"
    assert await svc.create_tenant(db=mock_db, payload=None) == "created"
    assert await svc.update_tenant(db=mock_db, id=1, payload=None) == "updated"
    assert await svc.delete_tenant(db=mock_db, id=1) == "deleted"
    assert await svc.get_by_email(db=mock_db, email="e") == "email"
    assert await svc.get_by_phone_number(db=mock_db, phone_number="p") == "phone"
    assert await svc.get_by_full_name(db=mock_db, full_name="n") == ["name"]
    assert await svc.get_by_occupation(db=mock_db, occupation="o") == ["occ"]

    assert await svc.get_by_date_of_birth(db=mock_db, date_of_birth=date(2000, 1, 1)) == ["dob"]
