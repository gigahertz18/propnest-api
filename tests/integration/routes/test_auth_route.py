from datetime import datetime, timedelta, timezone

from app.core.config import settings
from jose import jwt
from tests.factories import make_user_model, make_admin_model


class TestLogin:
    def test_login_with_username_succeeds(self, client, db):
        make_user_model(db, username="john", password="secret123")
        response = client.post(
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

    def test_login_with_email_succeeds(self, client, db):
        make_user_model(db, email="john@example.com", password="secret123")
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john@example.com",
                "password": "secret123",
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_with_wrong_password_fails(self, client, db):
        make_user_model(db, username="john")
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401

    def test_login_with_nonexistent_user_fails(self, client):
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "nobody",
                "password": "password",
            },
        )
        assert response.status_code == 401

    def test_login_is_case_insensitive_and_strips_whitespace(self, client, db):
        make_user_model(db, username="john", email="john@example.com", password="secret123")
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": " John@Example.Com ",
                "password": "secret123",
            },
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_with_inactive_account_fails(self, client, db):
        make_user_model(db, username="inactive", is_active=False)
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "inactive",
                "password": "password123",
            },
        )
        assert response.status_code == 403

    def test_error_message_is_generic(self, client, db):
        """Should not reveal whether the user exists."""
        make_user_model(db, username="john")
        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "wrongpassword",
            },
        )
        assert response.json()["detail"] == "Invalid credentials"


class TestMe:
    def test_returns_current_user(self, client, db):
        make_user_model(db, username="john", email="john@example.com")
        login = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "password123",
            },
        )
        token = login.json()["access_token"]
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["username"] == "john"

    def test_returns_403_without_token(self, client):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 403

    def test_password_not_in_response(self, client, db):
        make_user_model(db, username="john")
        login = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "john",
                "password": "password123",
            },
        )
        token = login.json()["access_token"]
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = response.json()
        assert "password" not in data
        assert "password_hash" not in data

    def test_returns_401_with_invalid_token(self, client):
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert response.status_code == 401

    def test_returns_401_for_token_with_invalid_sub_claim(self, client, db):
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

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid token payload"

    def test_returns_401_for_token_with_wrong_issuer(self, client, db):
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

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
