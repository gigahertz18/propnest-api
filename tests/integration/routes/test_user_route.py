import pytest
from tests.factories import make_user, make_user_model, make_admin_model


# ─── Helpers ──────────────────────────────────────────────
def login(client, identifier: str, password: str = "password123") -> str:
    """Returns a bearer token for the given identifier."""
    response = client.post("/api/v1/auth/login", json={
        "identifier": identifier,
        "password": password,
    })
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── List Users ───────────────────────────────────────────
class TestListUsersRoute:
    def test_admin_can_list_users(self, client, db):
        make_admin_model(db)
        make_user_model(db, username="user1", email="user1@example.com")
        token = login(client, "adminuser")
        response = client.get("/api/v1/users/", headers=auth_headers(token))
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_regular_user_cannot_list_users(self, client, db):
        make_user_model(db)
        token = login(client, "testuser")
        response = client.get("/api/v1/users/", headers=auth_headers(token))
        assert response.status_code == 403

    def test_unauthenticated_cannot_list_users(self, client):
        response = client.get("/api/v1/users/")
        assert response.status_code == 403


# ─── Get User ─────────────────────────────────────────────
class TestGetUserRoute:
    def test_admin_can_get_any_user(self, client, db):
        make_admin_model(db)
        user = make_user_model(db, username="other", email="other@example.com")
        token = login(client, "adminuser")
        response = client.get(f"/api/v1/users/{user.id}", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["id"] == user.id

    def test_user_can_get_themselves(self, client, db):
        user = make_user_model(db)
        token = login(client, "testuser")
        response = client.get(f"/api/v1/users/{user.id}", headers=auth_headers(token))
        assert response.status_code == 200

    def test_user_cannot_get_another_user(self, client, db):
        make_user_model(db, username="user1", email="user1@example.com")
        other = make_user_model(db, username="user2", email="user2@example.com")
        token = login(client, "user1")
        response = client.get(f"/api/v1/users/{other.id}", headers=auth_headers(token))
        assert response.status_code == 403

    def test_returns_404_when_not_found(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        response = client.get("/api/v1/users/nonexistent-id", headers=auth_headers(token))
        assert response.status_code == 404


# ─── Create User ──────────────────────────────────────────
class TestCreateUserRoute:
    def test_admin_can_create_user(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        response = client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="new@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["username"] == "newuser"

    def test_password_not_in_response(self, client, db):
        make_admin_model(db)
        token = login(client, "adminuser")
        response = client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="new@example.com"),
            headers=auth_headers(token),
        )
        data = response.json()
        assert "password" not in data
        assert "hashed_password" not in data

    def test_duplicate_email_returns_409(self, client, db):
        make_admin_model(db)
        make_user_model(db, username="existing", email="taken@example.com")
        token = login(client, "adminuser")
        response = client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="taken@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    def test_duplicate_username_returns_409(self, client, db):
        make_admin_model(db)
        make_user_model(db, username="taken", email="other@example.com")
        token = login(client, "adminuser")
        response = client.post(
            "/api/v1/users/",
            json=make_user(username="taken", email="new@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    def test_regular_user_cannot_create_user(self, client, db):
        make_user_model(db)
        token = login(client, "testuser")
        response = client.post(
            "/api/v1/users/",
            json=make_user(username="another", email="another@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 403


# ─── Update User ──────────────────────────────────────────
class TestUpdateUserRoute:
    def test_admin_can_update_any_user(self, client, db):
        make_admin_model(db)
        user = make_user_model(db, username="user1", email="user1@example.com")
        token = login(client, "adminuser")
        response = client.patch(
            f"/api/v1/users/{user.id}",
            json={"full_name": "Updated Name"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Updated Name"

    def test_user_can_update_themselves(self, client, db):
        user = make_user_model(db)
        token = login(client, "testuser")
        response = client.patch(
            f"/api/v1/users/{user.id}",
            json={"full_name": "New Name"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200

    def test_user_cannot_update_another_user(self, client, db):
        make_user_model(db, username="user1", email="user1@example.com")
        other = make_user_model(db, username="user2", email="user2@example.com")
        token = login(client, "user1")
        response = client.patch(
            f"/api/v1/users/{other.id}",
            json={"full_name": "Hacked"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    def test_user_cannot_change_their_own_role(self, client, db):
        user = make_user_model(db)
        token = login(client, "testuser")
        response = client.patch(
            f"/api/v1/users/{user.id}",
            json={"role": "admin"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403


# ─── Delete User ──────────────────────────────────────────
class TestDeleteUserRoute:
    def test_admin_can_delete_user(self, client, db):
        make_admin_model(db)
        user = make_user_model(db, username="todelete", email="delete@example.com")
        token = login(client, "adminuser")
        response = client.delete(
            f"/api/v1/users/{user.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 204

    def test_admin_cannot_delete_themselves(self, client, db):
        admin = make_admin_model(db)
        token = login(client, "adminuser")
        response = client.delete(
            f"/api/v1/users/{admin.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 400

    def test_regular_user_cannot_delete(self, client, db):
        make_user_model(db)
        other = make_user_model(db, username="other", email="other@example.com")
        token = login(client, "testuser")
        response = client.delete(
            f"/api/v1/users/{other.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    def test_deleted_user_is_gone(self, client, db):
        make_admin_model(db)
        user = make_user_model(db, username="todelete", email="delete@example.com")
        token = login(client, "adminuser")
        client.delete(f"/api/v1/users/{user.id}", headers=auth_headers(token))
        response = client.get(f"/api/v1/users/{user.id}", headers=auth_headers(token))
        assert response.status_code == 404
