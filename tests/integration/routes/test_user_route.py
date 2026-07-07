import pytest
import uuid

from tests.factories import make_user, make_user_model, make_admin_model
from tests.helpers import login, auth_headers

# ─── List Users ───────────────────────────────────────────


@pytest.mark.asyncio
class TestListUsersRoute:
    async def test_admin_can_list_users(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "adminuser")
        response = await client.get("/api/v1/users/", headers=auth_headers(token))
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_regular_user_cannot_list_users(self, client, db):
        await make_user_model(db)
        token = await login(client, "testuser")
        response = await client.get("/api/v1/users/", headers=auth_headers(token))
        assert response.status_code == 403

    async def test_unauthenticated_cannot_list_users(self, client):
        response = await client.get("/api/v1/users/")
        assert response.status_code == 403

    async def test_list_users_route_limit_zero_returns_empty(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "adminuser")

        response = await client.get(
            "/api/v1/users/?limit=0",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_users_route_clamps_limit_to_100(self, client, db):
        await make_admin_model(db)
        for i in range(105):
            await make_user_model(db, username=f"user{i}", email=f"user{i}@example.com")

        token = await login(client, "adminuser")

        response = await client.get(
            "/api/v1/users/?limit=150",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert len(response.json()) == 100

    async def test_list_users_route_negative_skip_is_treated_as_zero(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="first", email="first@example.com")
        await make_user_model(db, username="second", email="second@example.com")
        token = await login(client, "adminuser")

        response = await client.get(
            "/api/v1/users/?skip=-10&limit=1",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert len(response.json()) == 1


# ─── Get User ─────────────────────────────────────────────
@pytest.mark.asyncio
class TestGetUserRoute:
    async def test_admin_can_get_any_user(self, client, db):
        await make_admin_model(db)
        user = await make_user_model(db, username="other", email="other@example.com")
        token = await login(client, "adminuser")
        response = await client.get(f"/api/v1/users/{user.id}", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["id"] == str(user.id)

    async def test_user_can_get_themselves(self, client, db):
        user = await make_user_model(db)
        token = await login(client, "testuser")
        response = await client.get(f"/api/v1/users/{user.id}", headers=auth_headers(token))
        assert response.status_code == 200

    async def test_user_cannot_get_another_user(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com")
        other = await make_user_model(db, username="user2", email="user2@example.com")
        token = await login(client, "user1")
        response = await client.get(f"/api/v1/users/{other.id}", headers=auth_headers(token))
        assert response.status_code == 403

    async def test_returns_404_when_not_found(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        response = await client.get(
            f"/api/v1/users/{uuid.uuid4()}",
            headers=auth_headers(token),
        )
        assert response.status_code == 404


# ─── Create User ──────────────────────────────────────────
@pytest.mark.asyncio
class TestCreateUserRoute:
    async def test_admin_can_create_user(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="new@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["username"] == "newuser"

    async def test_password_not_in_response(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="new@example.com"),
            headers=auth_headers(token),
        )
        data = response.json()
        assert "password" not in data
        assert "password_hash" not in data

    async def test_duplicate_email_returns_409(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="existing", email="taken@example.com")
        token = await login(client, "adminuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="taken@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    async def test_duplicate_email_is_case_insensitive(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="existing", email="Taken@Example.Com")
        token = await login(client, "adminuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username="newuser", email="taken@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    async def test_duplicate_username_returns_409(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="taken", email="other@example.com")
        token = await login(client, "adminuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username="taken", email="new@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    async def test_duplicate_username_ignores_extra_whitespace(self, client, db):
        await make_admin_model(db)
        await make_user_model(db, username="takenuser", email="other@example.com")
        token = await login(client, "adminuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username=" TakenUser ", email="new@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    async def test_regular_user_cannot_create_user(self, client, db):
        await make_user_model(db)
        token = await login(client, "testuser")
        response = await client.post(
            "/api/v1/users/",
            json=make_user(username="another", email="another@example.com"),
            headers=auth_headers(token),
        )
        assert response.status_code == 403


# ─── Update User ──────────────────────────────────────────
@pytest.mark.asyncio
class TestUpdateUserRoute:
    async def test_admin_can_update_any_user(self, client, db):
        await make_admin_model(db)
        user = await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "adminuser")
        response = await client.patch(
            f"/api/v1/users/{user.id}",
            json={"full_name": "Updated Name"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Updated Name"

    async def test_user_can_update_themselves(self, client, db):
        user = await make_user_model(db)
        token = await login(client, "testuser")
        response = await client.patch(
            f"/api/v1/users/{user.id}",
            json={"full_name": "New Name"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200

    async def test_user_cannot_update_another_user(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com")
        other = await make_user_model(db, username="user2", email="user2@example.com")
        token = await login(client, "user1")
        response = await client.patch(
            f"/api/v1/users/{other.id}",
            json={"full_name": "Hacked"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    async def test_user_cannot_change_their_own_role(self, client, db):
        user = await make_user_model(db)
        token = await login(client, "testuser")
        response = await client.patch(
            f"/api/v1/users/{user.id}",
            json={"role": "admin"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    async def test_user_cannot_update_with_duplicate_email(self, client, db):
        user1 = await make_user_model(db, username="user1", email="user1@example.com")
        await make_user_model(db, username="user2", email="user2@example.com")
        token = await login(client, "user1")
        response = await client.patch(
            f"/api/v1/users/{user1.id}",
            json={"email": "user2@example.com"},
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    async def test_admin_cannot_update_to_duplicate_username(self, client, db):
        await make_admin_model(db)
        user1 = await make_user_model(db, username="user1", email="user1@example.com")
        await make_user_model(db, username="user2", email="user2@example.com")
        token = await login(client, "adminuser")
        response = await client.patch(
            f"/api/v1/users/{user1.id}",
            json={"username": "user2"},
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    async def test_admin_cannot_update_to_duplicate_email_with_different_case(self, client, db):
        await make_admin_model(db)
        user1 = await make_user_model(db, username="user1", email="user1@example.com")
        await make_user_model(db, username="user2", email="user2@example.com")
        token = await login(client, "adminuser")
        response = await client.patch(
            f"/api/v1/users/{user1.id}",
            json={"email": "USER2@EXAMPLE.COM"},
            headers=auth_headers(token),
        )
        assert response.status_code == 409


# ─── Delete User ──────────────────────────────────────────
@pytest.mark.asyncio
class TestDeleteUserRoute:
    async def test_admin_can_delete_user(self, client, db):
        await make_admin_model(db)
        user = await make_user_model(db, username="todelete", email="delete@example.com")
        token = await login(client, "adminuser")
        response = await client.delete(
            f"/api/v1/users/{user.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 204

    async def test_admin_cannot_delete_themselves(self, client, db):
        admin = await make_admin_model(db)
        token = await login(client, "adminuser")
        response = await client.delete(
            f"/api/v1/users/{admin.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 400

    async def test_regular_user_cannot_delete(self, client, db):
        await make_user_model(db)
        other = await make_user_model(db, username="other", email="other@example.com")
        token = await login(client, "testuser")
        response = await client.delete(
            f"/api/v1/users/{other.id}",
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    async def test_deleted_user_is_gone(self, client, db):
        await make_admin_model(db)
        user = await make_user_model(db, username="todelete", email="delete@example.com")
        token = await login(client, "adminuser")
        user_id = user.id
        await client.delete(f"/api/v1/users/{user_id}", headers=auth_headers(token))
        response = await client.get(f"/api/v1/users/{user_id}", headers=auth_headers(token))
        assert response.status_code == 404
