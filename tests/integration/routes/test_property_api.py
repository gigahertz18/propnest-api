import pytest
import uuid

from tests.factories import (
    make_property,
    make_property_model,
)


@pytest.mark.asyncio
class TestListPropertiesRoute:
    async def test_returns_empty_list(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get("/api/v1/properties/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json() == []

    async def test_returns_all_properties(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        await make_property_model(db, name="Unit A")
        await make_property_model(db, name="Unit B")

        response = await client.get("/api/v1/properties/", headers=ctx.headers)
        assert response.status_code == 200
        assert len(response.json()) == 2


@pytest.mark.asyncio
class TestGetPropertyRoute:
    async def test_returns_property_by_id(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        prop = await make_property_model(db)
        response = await client.get(f"/api/v1/properties/{prop.id}", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(prop.id)

    async def test_returns_404_when_not_found(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get(f"/api/v1/properties/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


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
