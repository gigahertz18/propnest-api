class TestUsersRoutes:
    def test_create_user_conflict_returns_409(self, client, set_override, admin_user):
        from app.core.dependencies import get_user_service, require_admin
        from app.services.exceptions import EmailAlreadyExistsError

        class FakeService:
            def create_user(self, db, payload):
                raise EmailAlreadyExistsError("duplicate")

        set_override(get_user_service, lambda: FakeService())
        set_override(require_admin, lambda: admin_user)

        payload = {
            "username": "u",
            "email": "dup@example.com",
            "full_name": "Dup",
            "password": "pw",
        }

        response = client.post("/api/v1/users/", json=payload)
        assert response.status_code == 409
        assert "email" in response.json()["detail"].lower() or "duplicate" in response.json()["detail"].lower()

    def test_update_user_not_found_returns_404(self, client, set_override, admin_user):
        from app.core.dependencies import get_user_service, get_current_user
        from app.services.exceptions import UserNotFoundError
        import uuid

        class FakeService:
            def update_user(self, db, user_id, payload):
                raise UserNotFoundError("not found")

        set_override(get_user_service, lambda: FakeService())
        set_override(get_current_user, lambda: admin_user)

        response = client.patch(f"/api/v1/users/{uuid.uuid4()}", json={})
        assert response.status_code == 404

    def test_delete_user_not_found_returns_404(self, client, set_override, admin_user):
        from app.core.dependencies import get_user_service, require_admin
        from app.services.exceptions import UserNotFoundError
        import uuid

        class FakeService:
            def delete_user(self, db, user_id):
                raise UserNotFoundError("not found")

        set_override(get_user_service, lambda: FakeService())
        set_override(require_admin, lambda: admin_user)

        response = client.delete(f"/api/v1/users/{uuid.uuid4()}")
        assert response.status_code == 404
