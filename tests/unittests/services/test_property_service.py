import pytest
from app.models.property import PropertyStatus
from app.services.property_service import PropertyService

@pytest.mark.asyncio
async def test_property_service_delegates_to_repo_methods(mock_db):
    class Repo:
        async def get_all(self, db, skip=0, limit=100):
            return ["p1"]

        async def get_by_id(self, db, id):
            return "byid"

        async def create(self, db, payload):
            return "created"

        async def update(self, db, id, payload):
            return "updated"

        async def delete(self, db, id):
            return "deleted"

        async def get_by_status(self, db, status):
            return ["s"]

    repo = Repo()
    svc = PropertyService(property_repo=repo)

    assert await svc.list_properties(db=mock_db) == ["p1"]
    assert await svc.get_property(db=mock_db, id=1) == "byid"
    assert await svc.create_property(db=mock_db, payload=None) == "created"
    assert await svc.update_property(db=mock_db, id=1, payload=None) == "updated"
    assert await svc.delete_property(db=mock_db, id=1) == "deleted"
    assert await svc.get_by_status(db=mock_db, status=PropertyStatus.vacant) == ["s"]
