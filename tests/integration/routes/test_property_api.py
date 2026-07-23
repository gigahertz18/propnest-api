import pytest
import uuid

from tests.factories import (
    make_property,
    make_property_model,
)


@pytest.mark.asyncio
class TestListPropertiesRoute:
    async def test_returns_empty_list(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get("/api/v1/properties/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_returns_all_properties(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await make_property_model(db, name="Unit A")
        await make_property_model(db, name="Unit B")

        response = await client.get("/api/v1/properties/", headers=ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 2

    async def test_returns_all_properties_with_pagination(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await make_property_model(db, name="Unit A")
        await make_property_model(db, name="Unit B")

        response = await client.get("/api/v1/properties/?skip=1&limit=1", headers=ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 1

    async def test_manager_can_list_only_owned_properties(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        other_mgr = await authenticate_manager(username="other_mgr", email="other_mgr@example.com")

        await make_property_model(db, name="Owned A", manager_id=mgr_ctx.user.id)
        await make_property_model(db, name="Owned B", manager_id=mgr_ctx.user.id)
        await make_property_model(db, name="Owned Other", manager_id=other_mgr.user.id)

        response = await client.get("/api/v1/properties/?skip=1&limit=1", headers=mgr_ctx.headers)

        assert response.status_code == 200
        resp_data = response.json()

        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 1
        assert resp_data["items"][0]["manager_id"] == str(mgr_ctx.user.id)


@pytest.mark.asyncio
class TestGetPropertyRoute:
    async def test_returns_property_by_id(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        response = await client.get(f"/api/v1/properties/{prop.id}", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(prop.id)

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/properties/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_returns_403_when_property_not_managed_by_manager(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await authenticate_manager(
            username="other_manager",
            email="other_manager@example.com",
        )
        prop = await make_property_model(db, manager_id=other_manager.user.id)

        response = await client.get(f"/api/v1/properties/{prop.id}", headers=ctx.headers)
        assert response.status_code == 403


@pytest.mark.asyncio
class TestCreatePropertyRoute:
    async def test_creates_property_successfully(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = make_property(name="New Unit")
        response = await client.post(
            "/api/v1/properties/",
            json=payload,
            headers=ctx.headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Unit"
        assert data["id"] is not None
        assert data["created_at"] is not None

    async def test_returns_422_when_name_missing(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = make_property()
        del payload["name"]
        response = await client.post(
            "/api/v1/properties/",
            json=payload,
            headers=ctx.headers,
        )
        assert response.status_code == 422

    async def test_default_status_is_vacant(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = make_property()
        response = await client.post(
            "/api/v1/properties/",
            json=payload,
            headers=ctx.headers,
        )
        assert response.json()["status"] == "vacant"

    async def test_create_returns_409_when_creating_existing_property(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await make_property_model(db, name="Existing Name", address="Existing St.")
        payload = make_property(name="Existing Name", address="Existing St.")

        response = await client.post(
            "/api/v1/properties/",
            json=payload,
            headers=ctx.headers,
        )

        assert response.status_code == 409


@pytest.mark.asyncio
class TestUpdatePropertyRoute:
    async def test_updates_name(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db, name="Old Name")
        response = await client.patch(
            f"/api/v1/properties/{prop.id}",
            json={"name": "New Name"},
            headers=ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    async def test_partial_update_does_not_affect_other_fields(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db, name="My Unit", address="123 Main St")
        response = await client.patch(
            f"/api/v1/properties/{prop.id}",
            json={"name": "Updated Unit"},
            headers=ctx.headers,
        )

        assert response.json()["address"] == "123 Main St"

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.patch(
            f"/api/v1/properties/{uuid.uuid4()}",
            json={"name": "Anything"},
            headers=ctx.headers,
        )
        assert response.status_code == 404

    async def test_update_returns_409_when_updating_with_same_name_and_address(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await make_property_model(db, name="Existing Name", address="Existing st.")
        prop = await make_property_model(db, name="Old Name", address="Old address")
        response = await client.patch(
            f"/api/v1/properties/{prop.id}",
            json={
                "name": "Existing Name",
                "address": "Existing st.",
            },
            headers=ctx.headers,
        )

        assert response.status_code == 409


@pytest.mark.asyncio
class TestDeletePropertyRoute:
    async def test_deletes_property_successfully(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        response = await client.delete(
            f"/api/v1/properties/{prop.id}",
            headers=ctx.headers,
        )
        assert response.status_code == 204

    async def test_deleted_property_is_gone(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        property_id = prop.id
        await client.delete(f"/api/v1/properties/{property_id}", headers=ctx.headers)
        response = await client.get(f"/api/v1/properties/{property_id}", headers=ctx.headers)
        assert response.status_code == 404

    async def test_returns_404_when_not_found(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.delete(
            f"/api/v1/properties/{uuid.uuid4()}",
            headers=ctx.headers,
        )
        assert response.status_code == 404


@pytest.mark.asyncio
class TestAssignManagerRoute:
    async def test_admin_assigns_manager_successfully(self, client, db, authenticate_admin, authenticate_manager):
        admin_ctx = await authenticate_admin()
        mgr_ctx = await authenticate_manager()

        prop = await make_property_model(db)

        response = await client.patch(
            f"/api/v1/properties/{prop.id}/assign-manager",
            json={"manager_id": str(mgr_ctx.user.id)},
            headers=admin_ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["manager_id"] == str(mgr_ctx.user.id)

    async def test_assigned_manager_can_then_list_and_access_property(
        self, client, db, authenticate_admin, authenticate_manager
    ):
        admin_ctx = await authenticate_admin()
        mgr_ctx = await authenticate_manager()
        prop = await make_property_model(db)

        assign_response = await client.patch(
            f"/api/v1/properties/{prop.id}/assign-manager",
            json={"manager_id": str(mgr_ctx.user.id)},
            headers=admin_ctx.headers,
        )

        assert assign_response.status_code == 200

        list_response = await client.get("/api/v1/properties/", headers=mgr_ctx.headers)
        assert list_response.status_code == 200
        list_data = list_response.json()
        assert list_data["total"] == 1
        assert list_data["items"][0]["id"] == str(prop.id)

    async def test_reassigning_overwrites_previous_manager(
        self,
        client,
        db,
        authenticate_admin,
        authenticate_manager,
    ):
        admin_ctx = await authenticate_admin()
        mgr_ctx = await authenticate_manager()
        second_mgr_ctx = await authenticate_manager(username="mgr2", email="mgr2@example.com")

        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)

        response = await client.patch(
            f"/api/v1/properties/{prop.id}/assign-manager",
            json={"manager_id": str(second_mgr_ctx.user.id)},
            headers=admin_ctx.headers,
        )

        assert response.status_code == 200
        assert response.json()["manager_id"] == str(second_mgr_ctx.user.id)

        first_mgr_access = await client.get(f"/api/v1/properties/{prop.id}", headers=mgr_ctx.headers)
        assert first_mgr_access.status_code == 403

    async def test_returns_404_when_property_not_found(self, client, authenticate_admin, authenticate_manager):
        admin_ctx = await authenticate_admin()
        mgr_ctx = await authenticate_manager()

        response = await client.patch(
            f"/api/v1/properties/{uuid.uuid4()}/assign-manager",
            json={"manager_id": str(mgr_ctx.user.id)},
            headers=admin_ctx.headers,
        )

        assert response.status_code == 404

    async def test_returns_404_when_assignee_user_does_not_exist(self, client, db, authenticate_admin):
        admin_ctx = await authenticate_admin()
        prop = await make_property_model(db)

        response = await client.patch(
            f"/api/v1/properties/{prop.id}/assign-manager",
            json={"manager_id": str(uuid.uuid4())},
            headers=admin_ctx.headers,
        )

        assert response.status_code == 404

    async def test_returns_400_when_assignee_is_not_a_manager(
        self,
        client,
        db,
        authenticate_admin,
        authenticate_user,
    ):
        admin_ctx = await authenticate_admin()
        user_ctx = await authenticate_user()
        prop = await make_property_model(db)

        response = await client.patch(
            f"/api/v1/properties/{prop.id}/assign-manager",
            json={"manager_id": str(user_ctx.user.id)},
            headers=admin_ctx.headers,
        )

        assert response.status_code == 400

    async def test_returns_403_when_caller_is_not_admin(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        prop = await make_property_model(db)

        response = await client.patch(
            f"/api/v1/properties/{prop.id}/assign-manager",
            json={"manager_id": str(mgr_ctx.user.id)},
            headers=mgr_ctx.headers,
        )

        assert response.status_code == 403
