import uuid
from app.repositories.property import property_repo
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.models.property import PropertyStatus
from tests.factories import make_property, make_property_model


class TestPropertyRepositoryGetAll:
    def test_returns_empty_list_when_no_properties(self, db):
        result = property_repo.get_all(db)
        assert result == []

    def test_returns_all_properties(self, db):
        make_property_model(db, name="Property A")
        make_property_model(db, name="Property B")
        result = property_repo.get_all(db)
        assert len(result) == 2

    def test_skip_and_limit(self, db):
        for i in range(5):
            make_property_model(db, name=f"Property {i}")
        result = property_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2


class TestPropertyRepositoryGetById:
    def test_returns_property_when_found(self, db):
        prop = make_property_model(db)
        result = property_repo.get_by_id(db, prop.id)
        assert result is not None
        assert result.id == prop.id

    def test_returns_none_when_not_found(self, db):
        result = property_repo.get_by_id(db, uuid.uuid4())
        assert result is None


class TestPropertyRepositoryCreate:
    def test_creates_property_successfully(self, db):
        payload = PropertyCreate(**make_property())
        result = property_repo.create(db, payload)
        assert result.id is not None
        assert result.name == "Test Property"
        assert result.status == PropertyStatus.vacant

    def test_created_property_is_persisted(self, db):
        payload = PropertyCreate(**make_property(name="Persisted"))
        created = property_repo.create(db, payload)
        fetched = property_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.name == "Persisted"

    def test_default_status_is_vacant(self, db):
        payload = PropertyCreate(**make_property())
        result = property_repo.create(db, payload)
        assert result.status == PropertyStatus.vacant


class TestPropertyRepositoryUpdate:
    def test_updates_specified_fields_only(self, db):
        prop = make_property_model(db, name="Old Name")
        payload = PropertyUpdate(name="New Name")
        result = property_repo.update(db, prop.id, payload)
        assert result.name == "New Name"
        assert result.address == prop.address

    def test_returns_none_when_property_not_found(self, db):
        payload = PropertyUpdate(name="New Name")
        result = property_repo.update(db, uuid.uuid4(), payload)
        assert result is None

    def test_update_status(self, db):
        prop = make_property_model(db)
        payload = PropertyUpdate(status=PropertyStatus.occupied)
        result = property_repo.update(db, prop.id, payload)
        assert result.status == PropertyStatus.occupied


class TestPropertyRepositoryDelete:
    def test_deletes_property_successfully(self, db):
        prop = make_property_model(db)
        property_id = prop.id
        result = property_repo.delete(db, property_id)
        assert result is not None
        assert property_repo.get_by_id(db, property_id) is None

    def test_returns_none_when_not_found(self, db):
        result = property_repo.delete(db, uuid.uuid4())
        assert result is None


class TestPropertyRepositoryCustomQueries:

    def test_get_by_status(self, db):
        make_property_model(db, status=PropertyStatus.vacant)
        make_property_model(db, status=PropertyStatus.occupied)
        result = property_repo.get_by_status(db, PropertyStatus.vacant)
        assert len(result) == 1
