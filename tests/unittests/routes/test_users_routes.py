from types import SimpleNamespace

from app.models.user import UserRole


def test_create_user_conflict_returns_409(client):
    from app.main import app
    from app.core.dependencies import get_user_service, require_admin
    from app.services.exceptions import EmailAlreadyExistsError

    class FakeService:
        def create_user(self, db, payload):
            raise EmailAlreadyExistsError("duplicate")

    # Provide admin context and fake service
    fake_admin = SimpleNamespace(id=None, role=UserRole.ADMIN)
    app.dependency_overrides[get_user_service] = lambda: FakeService()
    app.dependency_overrides[require_admin] = lambda: fake_admin

    payload = {
        "username": "u",
        "email": "dup@example.com",
        "full_name": "Dup",
        "password": "pw",
    }

    response = client.post("/api/v1/users/", json=payload)
    assert response.status_code == 409
    assert "email" in response.json()["detail"].lower() or "duplicate" in response.json()["detail"].lower()

    # cleanup overrides
    app.dependency_overrides.pop(get_user_service, None)
    app.dependency_overrides.pop(require_admin, None)
