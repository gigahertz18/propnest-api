import pytest
import uuid

from app.identity.models.user import UserRole
from tests.factories import (
    make_collection_model,
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_user_model,
)


@pytest.mark.asyncio
class TestListCollectionsRoute:
    async def test_returns_empty_list(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.get("/api/v1/collections/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_admin_sees_all_collections(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        await make_collection_model(db, property_id=prop.id, name="One")
        await make_collection_model(db, property_id=prop.id, name="Two")

        response = await client.get("/api/v1/collections/", headers=ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 2

    async def test_manager_sees_only_own_property_collections(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        own_prop = await make_property_model(db, manager_id=ctx.user.id)
        other_prop = await make_property_model(db, manager_id=other_manager.id)

        owned = await make_collection_model(db, property_id=own_prop.id)
        await make_collection_model(db, property_id=other_prop.id)

        response = await client.get("/api/v1/collections/", headers=ctx.headers)
        assert response.status_code == 200
        ids = {c["id"] for c in response.json()["items"]}
        assert ids == {str(owned.id)}

    async def test_regular_user_cannot_list_collections(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get("/api/v1/collections/", headers=ctx.headers)
        assert response.status_code == 403

    async def test_unauthenticated_cannot_list_collections(self, client):
        response = await client.get("/api/v1/collections/")
        assert response.status_code == 403


@pytest.mark.asyncio
class TestGetCollectionRoute:
    async def test_admin_can_get_any_collection(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        collection = await make_collection_model(db, property_id=prop.id)

        response = await client.get(f"/api/v1/collections/{collection.id}", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(collection.id)

    async def test_manager_can_get_collection_for_own_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)
        collection = await make_collection_model(db, property_id=prop.id)

        response = await client.get(f"/api/v1/collections/{collection.id}", headers=ctx.headers)
        assert response.status_code == 200

    async def test_manager_cannot_get_collection_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr2", email="othermgr2@example.com", role=UserRole.MANAGER
        )
        prop = await make_property_model(db, manager_id=other_manager.id)
        collection = await make_collection_model(db, property_id=prop.id)

        response = await client.get(f"/api/v1/collections/{collection.id}", headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/collections/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404


@pytest.mark.asyncio
class TestCreateCollectionRoute:
    async def test_manager_can_create_for_own_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)

        payload = {"name": "Lease Docs", "description": "Signed lease paperwork", "property_id": str(prop.id)}
        response = await client.post("/api/v1/collections/", json=payload, headers=ctx.headers)
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Lease Docs"
        assert body["property_id"] == str(prop.id)
        assert body["contract_id"] is None

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr3", email="othermgr3@example.com", role=UserRole.MANAGER
        )
        prop = await make_property_model(db, manager_id=other_manager.id)

        payload = {"name": "Lease Docs", "property_id": str(prop.id)}
        response = await client.post("/api/v1/collections/", json=payload, headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_property_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = {"name": "Lease Docs", "property_id": str(uuid.uuid4())}
        response = await client.post("/api/v1/collections/", json=payload, headers=ctx.headers)
        assert response.status_code == 404

    async def test_returns_400_when_contract_does_not_belong_to_property(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        other_prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=other_prop.id, tenant_id=tenant.id)

        payload = {"name": "Lease Docs", "property_id": str(prop.id), "contract_id": str(contract.id)}
        response = await client.post("/api/v1/collections/", json=payload, headers=ctx.headers)
        assert response.status_code == 400

    async def test_creates_with_matching_contract(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)

        payload = {"name": "Lease Docs", "property_id": str(prop.id), "contract_id": str(contract.id)}
        response = await client.post("/api/v1/collections/", json=payload, headers=ctx.headers)
        assert response.status_code == 201
        assert response.json()["contract_id"] == str(contract.id)


@pytest.mark.asyncio
class TestUpdateCollectionRoute:
    async def test_admin_can_update_name_and_description(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        collection = await make_collection_model(db, property_id=prop.id, name="Old")

        response = await client.patch(
            f"/api/v1/collections/{collection.id}",
            json={"name": "New", "description": "Updated"},
            headers=ctx.headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New"
        assert response.json()["description"] == "Updated"

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.patch(f"/api/v1/collections/{uuid.uuid4()}", json={"name": "New"}, headers=ctx.headers)
        assert response.status_code == 404

    async def test_manager_forbidden_for_unowned_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr4", email="othermgr4@example.com", role=UserRole.MANAGER
        )
        prop = await make_property_model(db, manager_id=other_manager.id)
        collection = await make_collection_model(db, property_id=prop.id)

        response = await client.patch(f"/api/v1/collections/{collection.id}", json={"name": "New"}, headers=ctx.headers)
        assert response.status_code == 403


@pytest.mark.asyncio
class TestDeleteCollectionRoute:
    async def test_admin_can_delete(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        collection = await make_collection_model(db, property_id=prop.id)

        response = await client.delete(f"/api/v1/collections/{collection.id}", headers=ctx.headers)
        assert response.status_code == 204

        get_response = await client.get(f"/api/v1/collections/{collection.id}", headers=ctx.headers)
        assert get_response.status_code == 404

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.delete(f"/api/v1/collections/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404
