import pytest
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from jose import jwt
from tests.factories import make_user_model

@pytest.mark.asyncio
class TestLogin:
    async def test_login_with_username_succeeds(self, client, db):
        await make_user_model(db, username="john", password="secret123")
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "secret123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_with_email_succeeds(self, client, db):
        await make_user_model(db, email="john@example.com", password="secret123")
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john@example.com",
                "password": "secret123",
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_login_with_wrong_password_fails(self, client, db):
        await make_user_model(db, username="john")
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401

    async def test_login_with_nonexistent_user_fails(self, client):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "nobody",
                "password": "password",
            },
        )
        assert response.status_code == 401

    async def test_login_is_case_insensitive_and_strips_whitespace(self, client, db):
        await make_user_model(db, username="john", email="john@example.com", password="secret123")
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": " John@Example.Com ",
                "password": "secret123",
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_login_with_inactive_account_fails(self, client, db):
        await make_user_model(db, username="inactive", is_active=False)
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "inactive",
                "password": "password123",
            },
        )
        assert response.status_code == 401

    async def test_error_message_is_generic(self, client, db):
        """Should not reveal whether the user exists."""
        await make_user_model(db, username="john")
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "wrongpassword",
            },
        )
        assert response.json()["detail"] == "Invalid credentials"

@pytest.mark.asyncio
class TestMe:
    async def test_returns_current_user(self, client, db):
        await make_user_model(db, username="john", email="john@example.com")
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "password123",
            },
        )
        token = login.json()["access_token"]
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["username"] == "john"

    async def test_returns_403_without_token(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 403

    async def test_password_not_in_response(self, client, db):
        await make_user_model(db, username="john")
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "password123",
            },
        )
        token = login.json()["access_token"]
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = response.json()
        assert "password" not in data
        assert "password_hash" not in data

    async def test_returns_401_with_invalid_token(self, client):
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert response.status_code == 401

    async def test_returns_401_for_token_with_invalid_sub_claim(self, client, db):
        payload = {
            "sub": "not-a-uuid",
            "role": "user",
            "username": "john",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid token payload"

    async def test_returns_401_for_token_with_wrong_issuer(self, client, db):
        payload = {
            "sub": "00000000-0000-0000-0000-000000000000",
            "role": "user",
            "username": "john",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "iat": datetime.now(timezone.utc),
            "iss": "bad-issuer",
            "aud": settings.JWT_AUDIENCE,
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
