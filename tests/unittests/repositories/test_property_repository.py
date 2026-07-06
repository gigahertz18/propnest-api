import pytest
import uuid
from app.repositories.property import property_repo
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import PropertyStatus
from tests.factories import make_property, make_property_model


@pytest.mark.asyncio
class TestPropertyRepositoryGetAll:
    async def test_returns_empty_list_when_no_properties(self, db):
        result = await property_repo.get_all(db)
        assert result == []

    async def test_returns_all_properties(self, db):
        await make_property_model(db, name="Property A")
        await make_property_model(db, name="Property B")
        result = await property_repo.get_all(db)
        assert len(result) == 2

    async def test_skip_and_limit(self, db):
        for i in range(5):
            await make_property_model(db, name=f"Property {i}")
        result = await property_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2


@pytest.mark.asyncio
class TestPropertyRepositoryGetById:
    async def test_returns_property_when_found(self, db):
        prop = await make_property_model(db)
        result = await property_repo.get_by_id(db, prop.id)
        assert result is not None
        assert result.id == prop.id

    async def test_returns_none_when_not_found(self, db):
        result = await property_repo.get_by_id(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestPropertyRepositoryCreate:
    async def test_creates_property_successfully(self, db):
        payload = PropertyCreate(**make_property())
        result = await property_repo.create(db, payload)
        assert result.id is not None
        assert result.name == "Test Property"
        assert result.status == PropertyStatus.vacant

    async def test_created_property_is_persisted(self, db):
        payload = PropertyCreate(**make_property(name="Persisted"))
        created = await property_repo.create(db, payload)
        fetched = await property_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.name == "Persisted"

    async def test_default_status_is_vacant(self, db):
        payload = PropertyCreate(**make_property())
        result = await property_repo.create(db, payload)
        assert result.status == PropertyStatus.vacant


@pytest.mark.asyncio
class TestPropertyRepositoryUpdate:
    async def test_updates_specified_fields_only(self, db):
        prop = await make_property_model(db, name="Old Name")
        payload = PropertyUpdate(name="New Name")
        result = await property_repo.update(db, prop.id, payload)
        assert result.name == "New Name"
        assert result.address == prop.address

    async def test_returns_none_when_property_not_found(self, db):
        payload = PropertyUpdate(name="New Name")
        result = await property_repo.update(db, uuid.uuid4(), payload)
        assert result is None

    async def test_update_status(self, db):
        prop = await make_property_model(db)
        payload = PropertyUpdate(status=PropertyStatus.occupied)
        result = await property_repo.update(db, prop.id, payload)
        assert result.status == PropertyStatus.occupied


@pytest.mark.asyncio
class TestPropertyRepositoryDelete:
    async def test_deletes_property_successfully(self, db):
        prop = await make_property_model(db)
        property_id = prop.id
        result = await property_repo.delete(db, property_id)
        assert result is not None
        assert await property_repo.get_by_id(db, property_id) is None

    async def test_returns_none_when_not_found(self, db):
        result = await property_repo.delete(db, uuid.uuid4())
        assert result is None


@pytest.mark.asyncio
class TestPropertyRepositoryCustomQueries:

    async def test_get_by_status(self, db):
        await make_property_model(db, status=PropertyStatus.vacant)
        await make_property_model(db, status=PropertyStatus.occupied)
        result = await property_repo.get_by_status(db, PropertyStatus.vacant)
        assert len(result) == 1
