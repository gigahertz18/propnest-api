import pytest

from uuid import uuid4
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.models.property import PropertyStatus
from app.services.property_service import PropertyService
from app.services.exceptions import RelatedResourceNotFoundError, PropertyAlreadyExistsError
from app.schemas.property import PropertyCreate, PropertyUpdate
from tests.mock_repos import MockCRUDRepo


class MockPropertyRepo(MockCRUDRepo):
    async def get_by_status(self, db, status):
        return await self._filter_by(status=status)


def _make_service(properties=None) -> PropertyService:
    return PropertyService(property_repo=MockPropertyRepo(properties or {}))


@pytest.mark.asyncio
class TestListProperties:
    async def test_returns_all_properties(self, mock_db):
        prop = SimpleNamespace(id=uuid4())
        svc = _make_service({prop.id: prop})
        assert await svc.list_properties(mock_db) == [prop]

    async def test_returns_empty_list_when_none_exist(self, mock_db):
        svc = _make_service()
        assert await svc.list_properties(mock_db) == []


@pytest.mark.asyncio
class TestGetProperty:
    async def test_returns_property_when_found(self, mock_db):
        prop = SimpleNamespace(id=uuid4())
        svc = _make_service({prop.id: prop})
        assert await svc.get_property(mock_db, prop.id) is prop

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_property(mock_db, uuid4())


@pytest.mark.asyncio
class TestCreateProperty:
    async def test_creates_and_commits(self, mock_db):
        svc = _make_service()
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        created = await svc.create_property(mock_db, payload)

        assert created.name == "Unit A"
        assert created.address == "123 Main St"
        assert mock_db.commit.called

    async def test_translates_duplicate_name_and_address(self, mock_db):
        class FailingRepo(MockPropertyRepo):
            async def create(self, db, payload):
                raise IntegrityError(
                    "INSERT",
                    {},
                    Exception('duplicate key value violates unique constraint "uq_property_name_address"'),
                )

        svc = PropertyService(property_repo=FailingRepo())
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        with pytest.raises(PropertyAlreadyExistsError):
            await svc.create_property(mock_db, payload)

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        class FailingRepo(MockPropertyRepo):
            async def create(self, db, payload):
                raise IntegrityError("INSERT", {}, Exception("some unrelated constraint violation"))

        svc = PropertyService(property_repo=FailingRepo())
        payload = PropertyCreate(name="Unit A", address="123 Main St")

        with pytest.raises(IntegrityError):
            await svc.create_property(mock_db, payload)


@pytest.mark.asyncio
class TestUpdateProperty:
    async def test_updates_existing_property(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), name="Old Name", address="Old Address")
        svc = PropertyService(property_repo=MockPropertyRepo({prop.id: prop}))
        payload = PropertyUpdate(name="New Name")

        updated = await svc.update_property(mock_db, prop.id, payload)

        assert updated.name == "New Name"
        assert mock_db.commit.called

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.update_property(mock_db, uuid4(), PropertyUpdate(name="New Name"))

    async def test_returns_none_when_repo_update_returns_none(self, mock_db):
        """Edge case: property existed at get_property time but the repo's
        update returns None anyway (e.g. deleted concurrently). The service
        doesn't paper over this — it returns None and lets the route 404."""
        prop = SimpleNamespace(id=uuid4())

        class Repo(MockPropertyRepo):
            async def update(self, db, id, payload):
                return None

        svc = PropertyService(property_repo=Repo({prop.id: prop}))

        result = await svc.update_property(mock_db, prop.id, PropertyUpdate(name="New Name"))

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

        svc = PropertyService(property_repo=FailingRepo({prop.id: prop}))

        with pytest.raises(PropertyAlreadyExistsError):
            await svc.update_property(mock_db, prop.id, PropertyUpdate(name="Unit A", address="123 Main St"))

    async def test_reraises_unrelated_integrity_errors(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        class FailingRepo(MockPropertyRepo):
            async def update(self, db, id, payload):
                raise IntegrityError("UPDATE", {}, Exception("some unrelated constraint violation"))

        svc = PropertyService(property_repo=FailingRepo({prop.id: prop}))

        with pytest.raises(IntegrityError):
            await svc.update_property(mock_db, prop.id, PropertyUpdate(name="Unit A"))


@pytest.mark.asyncio
class TestDeleteProperty:
    async def test_deletes_existing_property(self, mock_db):
        prop = SimpleNamespace(id=uuid4())
        svc = PropertyService(property_repo=MockPropertyRepo({prop.id: prop}))

        deleted = await svc.delete_property(mock_db, prop.id)

        assert deleted is prop
        assert mock_db.commit.called

    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.delete_property(mock_db, uuid4())

    async def test_returns_none_when_repo_delete_returns_none(self, mock_db):
        prop = SimpleNamespace(id=uuid4())

        class Repo(MockPropertyRepo):
            async def delete(self, db, id):
                return None

        svc = PropertyService(property_repo=Repo({prop.id: prop}))

        result = await svc.delete_property(mock_db, prop.id)

        assert result is None


@pytest.mark.asyncio
class TestGetByStatus:
    async def test_delegates_to_repo(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), status=PropertyStatus.vacant)
        svc = _make_service({prop.id: prop})
        assert await svc.get_by_status(mock_db, PropertyStatus.vacant) == [prop]

    async def test_returns_empty_list_when_none_match(self, mock_db):
        prop = SimpleNamespace(id=uuid4(), status=PropertyStatus.occupied)
        svc = _make_service({prop.id: prop})
        assert await svc.get_by_status(mock_db, PropertyStatus.vacant) == []
