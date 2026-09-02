import pytest

from types import SimpleNamespace
from uuid import uuid4

from app.collections.schemas.collection import CollectionCreate, CollectionUpdate
from app.collections.services.collection_service import CollectionService
from app.core.services.exceptions import (
    CollectionForbiddenError,
    CollectionValidationError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager, make_regular_user


class MockCollectionRepo(MockCRUDRepo):
    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return [c for c in self.records.values() if getattr(c, "manager_id", None) == manager_id]


def _make_service(collections=None, properties=None, contracts=None) -> CollectionService:
    if collections is None:
        collection_repo = MockCollectionRepo({})
    elif isinstance(collections, dict):
        collection_repo = MockCollectionRepo(collections)
    else:
        collection_repo = collections

    if properties is None:
        property_repo = MockReadOnlyRepo({})
    elif isinstance(properties, dict):
        property_repo = MockReadOnlyRepo(properties)
    else:
        property_repo = properties

    if contracts is None:
        contract_repo = MockReadOnlyRepo({})
    elif isinstance(contracts, dict):
        contract_repo = MockReadOnlyRepo(contracts)
    else:
        contract_repo = contracts

    return CollectionService(
        collection_repo=collection_repo,
        property_repo=property_repo,
        contract_repo=contract_repo,
    )


def _payload(**kwargs):
    defaults = dict(name="Lease Docs", description=None, property_id=uuid4(), contract_id=None)
    defaults.update(kwargs)
    return CollectionCreate(**defaults)


# ─── Construction / class attributes ─────────────────────────────────────────


class TestCollectionServiceClassAttributes:
    def test_forbidden_error_is_collection_forbidden_error(self):
        assert CollectionService.forbidden_error is CollectionForbiddenError

    def test_collection_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(CollectionForbiddenError, ResourceForbiddenError)

    def test_property_repo_and_contract_repo_default_to_none(self):
        svc = CollectionService(collection_repo=MockCollectionRepo())
        assert svc.property_repo is None
        assert svc.contract_repo is None


# ─── get_collection ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetCollection:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_collection(mock_db, uuid4(), make_admin())

    async def test_admin_can_access_any_collection(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.get_collection(mock_db, collection.id, make_admin())
        assert result is collection

    async def test_manager_can_access_collection_for_owned_property(self, mock_db):
        manager_id, prop_id = uuid4(), uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
        )

        result = await svc.get_collection(mock_db, collection.id, make_manager(manager_id))
        assert result is collection

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(CollectionForbiddenError):
            await svc.get_collection(mock_db, collection.id, make_manager())

    async def test_regular_user_is_forbidden(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(CollectionForbiddenError):
            await svc.get_collection(mock_db, collection.id, make_regular_user())


# ─── create_collection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateCollection:
    async def test_raises_when_property_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_collection(mock_db, _payload(), make_admin())

    async def test_admin_can_create_for_any_property(self, mock_db):
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})

        result = await svc.create_collection(mock_db, _payload(property_id=prop_id), make_admin())
        assert result.property_id == prop_id
        assert mock_db.commit.called

    async def test_manager_can_create_for_owned_property(self, mock_db):
        manager_id, prop_id = uuid4(), uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)})

        result = await svc.create_collection(mock_db, _payload(property_id=prop_id), make_manager(manager_id))
        assert result.property_id == prop_id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})
        repo = svc.collection_repo

        with pytest.raises(CollectionForbiddenError):
            await svc.create_collection(mock_db, _payload(property_id=prop_id), make_manager())

        assert repo.created_payloads == []
        assert not mock_db.commit.called

    async def test_raises_when_contract_not_found(self, mock_db):
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_collection(mock_db, _payload(property_id=prop_id, contract_id=uuid4()), make_admin())

    async def test_raises_when_contract_belongs_to_different_property(self, mock_db):
        prop_id, other_prop_id, contract_id = uuid4(), uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=other_prop_id)},
        )

        with pytest.raises(CollectionValidationError):
            await svc.create_collection(mock_db, _payload(property_id=prop_id, contract_id=contract_id), make_admin())

    async def test_creates_with_matching_contract(self, mock_db):
        prop_id, contract_id = uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
        )

        result = await svc.create_collection(
            mock_db, _payload(property_id=prop_id, contract_id=contract_id), make_admin()
        )
        assert result.contract_id == contract_id


# ─── update_collection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateCollection:
    async def test_updates_name_and_description(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None, name="Old")
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.update_collection(mock_db, collection.id, CollectionUpdate(name="New"), make_admin())
        assert result.name == "New"
        assert mock_db.commit.called

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None, name="Old")
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        with pytest.raises(CollectionForbiddenError):
            await svc.update_collection(mock_db, collection.id, CollectionUpdate(name="New"), make_manager())

    async def test_raises_when_new_contract_belongs_to_different_property(self, mock_db):
        prop_id, other_prop_id, contract_id = uuid4(), uuid4(), uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=other_prop_id)},
        )

        with pytest.raises(CollectionValidationError):
            await svc.update_collection(mock_db, collection.id, CollectionUpdate(contract_id=contract_id), make_admin())

    async def test_updates_contract_id_when_matching_property(self, mock_db):
        prop_id, contract_id = uuid4(), uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
        )

        result = await svc.update_collection(
            mock_db, collection.id, CollectionUpdate(contract_id=contract_id), make_admin()
        )
        assert result.contract_id == contract_id


# ─── delete_collection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteCollection:
    async def test_admin_can_delete(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )

        result = await svc.delete_collection(mock_db, collection.id, make_admin())
        assert result is collection
        assert mock_db.commit.called

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        collection = SimpleNamespace(id=uuid4(), property_id=prop_id, contract_id=None)
        svc = _make_service(
            collections={collection.id: collection},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        repo = svc.collection_repo

        with pytest.raises(CollectionForbiddenError):
            await svc.delete_collection(mock_db, collection.id, make_manager())

        assert repo.deleted_ids == []


# ─── list_collections ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListCollections:
    async def test_manager_role_uses_manager_scoping(self, mock_db):
        manager_id = uuid4()
        owned = SimpleNamespace(id=uuid4(), manager_id=manager_id)
        not_owned = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        repo = MockCollectionRepo({owned.id: owned, not_owned.id: not_owned})
        svc = _make_service(collections=repo)

        result = await svc.list_collections(mock_db, make_manager(manager_id))
        assert [i.id for i in result.items] == [owned.id]
        assert result.total == 1

    async def test_regular_user_is_forbidden(self, mock_db):
        svc = _make_service()
        with pytest.raises(CollectionForbiddenError):
            await svc.list_collections(mock_db, make_regular_user())
