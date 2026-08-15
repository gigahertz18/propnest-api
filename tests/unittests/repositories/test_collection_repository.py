import pytest
import pytest_asyncio
import uuid

from app.repositories.collection import collection_repo
from app.schemas.collection import CollectionCreate, CollectionUpdate
from tests.factories import (
    make_collection,
    make_collection_model,
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_manager_model,
)

# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def manager(db):
    return await make_manager_model(db)


@pytest_asyncio.fixture
async def property_(db, manager):
    return await make_property_model(db, manager_id=manager.id)


@pytest_asyncio.fixture
async def tenant(db):
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def contract(db, property_, tenant):
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


@pytest_asyncio.fixture
async def collection(db, property_):
    return await make_collection_model(db, property_id=property_.id)


# ─── get_all ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryGetAll:
    async def test_returns_empty_list_when_no_collections(self, db):
        result = await collection_repo.get_all(db)
        assert list(result) == []

    async def test_returns_all_collections(self, db, property_):
        await make_collection_model(db, property_id=property_.id, name="One")
        await make_collection_model(db, property_id=property_.id, name="Two")

        result = await collection_repo.get_all(db)
        assert len(result) == 2


# ─── create ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryCreate:
    async def test_creates_collection_with_required_property_id(self, db, property_):
        payload = CollectionCreate(**make_collection(property_id=property_.id))
        result = await collection_repo.create(db, payload)

        assert result.id is not None
        assert result.property_id == property_.id
        assert result.contract_id is None
        assert result.name == "Test Collection"

    async def test_creates_collection_with_contract_id(self, db, property_, contract):
        payload = CollectionCreate(**make_collection(property_id=property_.id, contract_id=contract.id))
        result = await collection_repo.create(db, payload)

        assert result.contract_id == contract.id


# ─── get_by_id ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryGetById:
    async def test_returns_none_when_not_found(self, db):
        result = await collection_repo.get_by_id(db, uuid.uuid4())
        assert result is None

    async def test_returns_collection_when_found(self, db, collection):
        result = await collection_repo.get_by_id(db, collection.id)
        assert result is not None
        assert result.id == collection.id


# ─── update ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryUpdate:
    async def test_updates_name_and_description(self, db, collection):
        result = await collection_repo.update(
            db, collection.id, CollectionUpdate(name="Renamed", description="New desc")
        )
        assert result is not None
        assert result.name == "Renamed"
        assert result.description == "New desc"

    async def test_updates_contract_id(self, db, collection, contract):
        result = await collection_repo.update(db, collection.id, CollectionUpdate(contract_id=contract.id))
        assert result is not None
        assert result.contract_id == contract.id

    async def test_returns_none_when_not_found(self, db):
        result = await collection_repo.update(db, uuid.uuid4(), CollectionUpdate(name="X"))
        assert result is None


# ─── delete ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryDelete:
    async def test_deletes_existing_collection(self, db, collection):
        result = await collection_repo.delete(db, collection.id)
        assert result is not None
        assert await collection_repo.get_by_id(db, collection.id) is None

    async def test_returns_none_when_not_found(self, db):
        result = await collection_repo.delete(db, uuid.uuid4())
        assert result is None


# ─── get_by_property / get_by_contract ───────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryQueries:
    async def test_get_by_property_returns_matching_collections(self, db, property_):
        c1 = await make_collection_model(db, property_id=property_.id)
        other_property = await make_property_model(db)
        await make_collection_model(db, property_id=other_property.id)

        result = await collection_repo.get_by_property(db, property_.id)
        ids = {c.id for c in result}
        assert ids == {c1.id}

    async def test_get_by_contract_returns_matching_collections(self, db, property_, contract):
        c1 = await make_collection_model(db, property_id=property_.id, contract_id=contract.id)
        await make_collection_model(db, property_id=property_.id)

        result = await collection_repo.get_by_contract(db, contract.id)
        ids = {c.id for c in result}
        assert ids == {c1.id}


# ─── manager scoping ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionRepositoryManagerScoping:
    async def test_get_all_for_manager_returns_only_owned_property_collections(self, db, manager, property_):
        owned = await make_collection_model(db, property_id=property_.id)
        other_manager = await make_manager_model(db, username="othermgr", email="othermgr@example.com")
        other_property = await make_property_model(db, manager_id=other_manager.id)
        await make_collection_model(db, property_id=other_property.id)

        result = await collection_repo.get_all_for_manager(db, manager.id)
        ids = {c.id for c in result}
        assert ids == {owned.id}

    async def test_count_all_for_manager_matches(self, db, manager, property_):
        await make_collection_model(db, property_id=property_.id)
        await make_collection_model(db, property_id=property_.id)
        other_manager = await make_manager_model(db, username="othermgr2", email="othermgr2@example.com")
        other_property = await make_property_model(db, manager_id=other_manager.id)
        await make_collection_model(db, property_id=other_property.id)

        count = await collection_repo.count_all_for_manager(db, manager.id)
        assert count == 2

    async def test_count_all_matches_total_records(self, db, property_):
        await make_collection_model(db, property_id=property_.id)
        await make_collection_model(db, property_id=property_.id)

        count = await collection_repo.count_all(db)
        assert count == 2
