import uuid

from tests.factories import (
    make_property,
    make_property_model,
    make_admin_model,
    make_user_model,
)
from app.models.property import RentalType, PropertyStatus


# ─── Helpers ──────────────────────────────────────────────
def login(client, identifier: str, password: str = "password123") -> str:
    """Returns a bearer token for the given identifier."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": identifier,
            "password": password,
        },
    )
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestListPropertiesRoute:
    def test_returns_empty_list(self, client):
        response = client.get("/api/v1/properties/")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_all_properties(self, client, db):
        make_property_model(db, name="Unit A")
        make_property_model(db, name="Unit B")
        response = client.get("/api/v1/properties/")
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestGetPropertyRoute:
    def test_returns_property_by_id(self, client, db):
        prop = make_property_model(db)
        response = client.get(f"/api/v1/properties/{prop.id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(prop.id)

    def test_returns_404_when_not_found(self, client):
        response = client.get(f"/api/v1/properties/{uuid.uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestCreatePropertyRoute:
    def test_creates_property_successfully(self, client, db):
        make_admin_model(db)
        user = make_user_model(db, username="user1", email="user1@example.com")
        token = login(client, "adminuser")
        payload = make_property(name="New Unit")
        response = client.post(
            "/api/v1/properties/",
            json=payload,
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Unit"
        assert data["id"] is not None
        assert data["created_at"] is not None

    def test_returns_422_when_name_missing(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        payload = make_property()
        del payload["name"]
        response = client.post(
            "/api/v1/properties/",
            json=payload,
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_returns_422_when_invalid_rental_type(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        payload = make_property()
        payload["rental_type"] = "invalid_type"
        response = client.post(
            "/api/v1/properties/",
            json=payload,
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_default_status_is_vacant(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        payload = make_property()
        response = client.post(
            "/api/v1/properties/",
            json=payload,
            headers=auth_headers(token),
        )
        assert response.json()["status"] == "vacant"


class TestUpdatePropertyRoute:
    def test_updates_name(self, client, db):
        prop = make_property_model(db, name="Old Name")
        response = client.patch(
            f"/api/v1/properties/{prop.id}",
            json={"name": "New Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_partial_update_does_not_affect_other_fields(self, client, db):
        prop = make_property_model(db, name="My Unit", address="123 Main St")
        response = client.patch(
            f"/api/v1/properties/{prop.id}",
            json={"name": "Updated Unit"},
        )
        assert response.json()["address"] == "123 Main St"

    def test_returns_404_when_not_found(self, client):
        response = client.patch(
            f"/api/v1/properties/{uuid.uuid4()}",
            json={"name": "Anything"},
        )
        assert response.status_code == 404


class TestDeletePropertyRoute:
    def test_deletes_property_successfully(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        prop = make_property_model(db)
        response = client.delete(
            f"/api/v1/properties/{prop.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 204

    def test_deleted_property_is_gone(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        prop = make_property_model(db)
        property_id = prop.id
        client.delete(f"/api/v1/properties/{property_id}", headers=auth_headers(token))
        response = client.get(f"/api/v1/properties/{property_id}")
        assert response.status_code == 404

    def test_returns_404_when_not_found(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        response = client.delete(
            f"/api/v1/properties/{uuid.uuid4()}",
            headers=auth_headers(token),
        )
        assert response.status_code == 404
