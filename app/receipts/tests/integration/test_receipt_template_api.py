import pytest

from app.core.dependencies import get_storage_client
from app.main import app
from tests.factories import make_manager_model, make_property_model


class FakeStorageClient:
    """Minimal stand-in for the MinIO client — only what ReceiptTemplateService touches."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, bucket, key, stream, length, content_type=None):
        self.objects[key] = stream.read()

    def get_object(self, bucket, key):
        data = self.objects[key]

        class _Response:
            def read(self_inner):
                return data

            def close(self_inner):
                pass

            def release_conn(self_inner):
                pass

        return _Response()

    def remove_object(self, bucket, key):
        self.objects.pop(key, None)


@pytest.fixture(autouse=True)
def _override_storage_client():
    app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()
    yield
    app.dependency_overrides.pop(get_storage_client, None)


def _template_file(content: bytes = b"<html><body>{{ receipt_number }}</body></html>"):
    return {"file": ("template.html", content, "text/html")}


@pytest.mark.asyncio
class TestUploadReceiptTemplateRoute:
    async def test_admin_can_upload_global_template(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.post(
            "/api/v1/receipt-templates/",
            data={"name": "Global Default"},
            files=_template_file(),
            headers=auth_ctx.headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["property_id"] is None
        assert body["is_active"] is False

    async def test_manager_cannot_upload_global_template(self, client, authenticate_manager):
        auth_ctx = await authenticate_manager()
        response = await client.post(
            "/api/v1/receipt-templates/",
            data={"name": "Global Default"},
            files=_template_file(),
            headers=auth_ctx.headers,
        )
        assert response.status_code == 403

    async def test_manager_can_upload_for_owned_property(self, client, db, authenticate_manager):
        auth_ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=auth_ctx.user.id)

        response = await client.post(
            "/api/v1/receipt-templates/",
            data={"name": "Branded", "property_id": str(prop.id)},
            files=_template_file(),
            headers=auth_ctx.headers,
        )
        assert response.status_code == 201
        assert response.json()["property_id"] == str(prop.id)

    async def test_manager_forbidden_for_unowned_property(self, client, db, authenticate_manager):
        auth_ctx = await authenticate_manager()
        other_mgr = await make_manager_model(db, username="othermgr", email="othermgr@example.com")
        prop = await make_property_model(db, manager_id=other_mgr.id)

        response = await client.post(
            "/api/v1/receipt-templates/",
            data={"name": "Branded", "property_id": str(prop.id)},
            files=_template_file(),
            headers=auth_ctx.headers,
        )
        assert response.status_code == 403

    async def test_regular_user_forbidden(self, client, authenticate_user):
        auth_ctx = await authenticate_user()
        response = await client.post(
            "/api/v1/receipt-templates/",
            data={"name": "x"},
            files=_template_file(),
            headers=auth_ctx.headers,
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestActivateReceiptTemplateRoute:
    async def test_activating_deactivates_the_previous_active_template(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        first = (
            await client.post(
                "/api/v1/receipt-templates/", data={"name": "A"}, files=_template_file(), headers=auth_ctx.headers
            )
        ).json()
        second = (
            await client.post(
                "/api/v1/receipt-templates/", data={"name": "B"}, files=_template_file(), headers=auth_ctx.headers
            )
        ).json()

        await client.post(f"/api/v1/receipt-templates/{first['id']}/activate", headers=auth_ctx.headers)
        activate_second = await client.post(
            f"/api/v1/receipt-templates/{second['id']}/activate", headers=auth_ctx.headers
        )
        assert activate_second.status_code == 200
        assert activate_second.json()["is_active"] is True

        first_after = await client.get(f"/api/v1/receipt-templates/{first['id']}", headers=auth_ctx.headers)
        assert first_after.json()["is_active"] is False

    async def test_returns_404_for_unknown_template(self, client, authenticate_admin):
        import uuid

        auth_ctx = await authenticate_admin()
        response = await client.post(f"/api/v1/receipt-templates/{uuid.uuid4()}/activate", headers=auth_ctx.headers)
        assert response.status_code == 404


@pytest.mark.asyncio
class TestListAndGetReceiptTemplateRoutes:
    async def test_manager_can_list_for_owned_property(self, client, db, authenticate_manager):
        auth_ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=auth_ctx.user.id)
        await client.post(
            "/api/v1/receipt-templates/",
            data={"name": "Branded", "property_id": str(prop.id)},
            files=_template_file(),
            headers=auth_ctx.headers,
        )

        response = await client.get(f"/api/v1/receipt-templates/?property_id={prop.id}", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_manager_forbidden_from_listing_everything(self, client, authenticate_manager):
        auth_ctx = await authenticate_manager()
        response = await client.get("/api/v1/receipt-templates/", headers=auth_ctx.headers)
        assert response.status_code == 403

    async def test_get_returns_404_when_not_found(self, client, authenticate_admin):
        import uuid

        auth_ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/receipt-templates/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404
