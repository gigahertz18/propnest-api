import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.dependencies import get_storage_client, get_document_service
from app.main import app
from app.models.user import UserRole
from tests.factories import (
    make_document,
    make_document_model,
    make_property_model,
    make_admin_model,
    make_user_model,
)

from tests.helpers import login, auth_headers


# ─── Shared helpers ───────────────────────────────────────────────────────────


async def _make_manager(db, username="manager1", email="manager1@example.com"):
    return await make_user_model(db, username=username, email=email, role=UserRole.MANAGER)


class FakeStorageClient:
    """Minimal stand-in for the MinIO client — only what DocumentService touches."""

    def __init__(self, raise_on_put: Exception | None = None, raise_on_remove: Exception | None = None):
        self.raise_on_put = raise_on_put
        self.raise_on_remove = raise_on_remove
        self.put_calls: list[tuple] = []
        self.remove_calls: list[tuple] = []

    def put_object(self, *args, **kwargs):
        if self.raise_on_put:
            raise self.raise_on_put
        self.put_calls.append((args, kwargs))

    def remove_object(self, *args, **kwargs):
        if self.raise_on_remove:
            raise self.raise_on_remove
        self.remove_calls.append((args, kwargs))


# ─── GET /documents/ ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListDocumentsRoute:
    async def test_returns_empty_list(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "user1")
        response = await client.get("/api/v1/documents/", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json() == []

    async def test_returns_all_documents(self, client, db):
        await make_document_model(db, file_name="a.pdf")
        await make_document_model(db, file_name="b.pdf")
        await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "user1")
        response = await client.get("/api/v1/documents/", headers=auth_headers(token))
        assert response.status_code == 200
        assert len(response.json()) == 2


# ─── GET /documents/{id} ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetDocumentRoute:
    async def test_returns_document_by_id(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "user1")
        doc = await make_document_model(db)
        response = await client.get(f"/api/v1/documents/{doc.id}", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["id"] == str(doc.id)

    async def test_returns_404_when_not_found(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com")
        token = await login(client, "user1")
        response = await client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_headers(token))
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

# ─── POST /documents/ (JSON metadata-only create) ────────────────────────────


@pytest.mark.asyncio
class TestCreateDocumentRoute:
    async def test_creates_document_successfully(self, client, db):
        await make_admin_model(db)
        prop = await make_property_model(db)
        token = await login(client, "adminuser")
        payload = make_document(file_name="new.pdf")
        payload["contract_id"] = None
        payload["property_id"] = str(prop.id)
        payload["tenant_id"] = None
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_headers(token))
        assert response.status_code == 201
        data = response.json()
        assert data["file_name"] == "new.pdf"
        assert data["id"] is not None

    async def test_returns_422_when_file_name_missing(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        payload = make_document()
        del payload["file_name"]
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_headers(token))
        assert response.status_code == 422

    async def test_returns_403_for_regular_user(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com", role=UserRole.USER)
        token = await login(client, "user1")
        payload = make_document()
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_headers(token))
        assert response.status_code == 403

    async def test_manager_can_create_for_their_own_property(self, client, db):
        manager = await _make_manager(db)
        prop = await make_property_model(db, manager_id=manager.id)
        token = await login(client, "manager1")
        payload = make_document(property_id=str(prop.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_headers(token))
        assert response.status_code == 201

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db):
        owner = await _make_manager(db, username="owner", email="owner@example.com")
        outsider = await _make_manager(db, username="outsider", email="outsider@example.com")
        prop = await make_property_model(db, manager_id=owner.id)
        token = await login(client, "outsider")
        payload = make_document(property_id=str(prop.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_headers(token))
        assert response.status_code == 403

    async def test_returns_404_when_property_not_found(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        payload = make_document(property_id=str(uuid.uuid4()))

        response = await client.post("/api/v1/documents/", json=payload, headers=auth_headers(token))

        assert response.status_code == 404


# ─── POST /documents/upload (multipart upload) ───────────────────────────────


@pytest.mark.asyncio
class TestUploadDocumentRoute:
    async def test_uploads_document_successfully(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["file_name"] == "upload.pdf"

    async def test_returns_503_when_storage_upload_fails(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(
            raise_on_put=Exception("storage is down")
        )

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 503

    async def test_returns_422_when_filename_missing(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422
    
    async def test_returns_404_when_property_not_found(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()
        
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf", "property_id": str(uuid.uuid4())},
            headers=auth_headers(token),
        )
        
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db):
        owner = await _make_manager(db, username="owner", email="owner@example.com")
        outsider = await _make_manager(db, username="outsider", email="outsider@example.com")
        prop = await make_property_model(db, manager_id=owner.id)
        token = await login(client, "outsider")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf", "property_id": str(prop.id)},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    async def test_returns_403_for_regular_user(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com", role=UserRole.USER)
        token = await login(client, "user1")

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403


# ─── PATCH /documents/{id} ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateDocumentRoute:
    async def test_relink_to_different_property(self, client, db):
        await make_admin_model(db)
        prop = await make_property_model(db)
        new_prop = await make_property_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db, file_name="old.pdf", property_id=prop.id)
        response = await client.patch(
            f"/api/v1/documents/{doc.id}",
            json={"property_id": str(new_prop.id)},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["property_id"] == str(new_prop.id)

    async def test_returns_404_when_not_found(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        response = await client.patch(
            f"/api/v1/documents/{uuid.uuid4()}",
            json={"property_id": str(uuid.uuid4())},
            headers=auth_headers(token),
        )
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db):
            owner = await _make_manager(db, username="owner", email="owner@example.com")
            outsider = await _make_manager(db, username="outsider", email="outsider@example.com")
            prop = await make_property_model(db, manager_id=owner.id)
            doc = await make_document_model(db, property_id=prop.id)
            token = await login(client, "outsider")

            response = await client.patch(
                f"/api/v1/documents/{doc.id}",
                json={"property_id": str(prop.id)},
                headers=auth_headers(token),
            )
            assert response.status_code == 403
            
# ─── DELETE /documents/{id} ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDeleteDocumentRoute:
    async def test_deletes_document_successfully(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db)

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.delete(f"/api/v1/documents/{doc.id}", headers=auth_headers(token))
        assert response.status_code == 204

    async def test_deleted_document_is_gone(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db)
        document_id = doc.id

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        await client.delete(f"/api/v1/documents/{document_id}", headers=auth_headers(token))
        response = await client.get(f"/api/v1/documents/{document_id}", headers=auth_headers(token))
        assert response.status_code == 404

    async def test_returns_404_when_not_found(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        response = await client.delete(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_headers(token))
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db):
        owner = await _make_manager(db, username="owner", email="owner@example.com")
        outsider = await _make_manager(db, username="outsider", email="outsider@example.com")
        prop = await make_property_model(db, manager_id=owner.id)
        doc = await make_document_model(db, property_id=prop.id)
        token = await login(client, "outsider")

        response = await client.delete(f"/api/v1/documents/{doc.id}", headers=auth_headers(token))
        assert response.status_code == 403

    async def test_returns_503_when_storage_deletion_fails(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db)

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(
            raise_on_remove=Exception("storage is down")
        )

        response = await client.delete(f"/api/v1/documents/{doc.id}", headers=auth_headers(token))
        assert response.status_code == 503
# ─── PATCH /{id}/file ───────────────────────────────────────────────────
@pytest.mark.asyncio
class TestReplaceDocumentFileRoute:
    async def test_replaces_file_successfully(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db, file_name="old.pdf")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 new content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["file_name"] == "new.pdf"

    async def test_returns_422_when_filename_missing(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db)
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("", b"content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422  # FastAPI validates this before your 400 check fires — verify which actually wins

    async def test_returns_404_when_document_not_found(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{uuid.uuid4()}/file",
            files={"file": ("new.pdf", b"content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized(self, client, db):
        owner = await _make_manager(db, username="owner", email="owner@example.com")
        outsider = await _make_manager(db, username="outsider", email="outsider@example.com")
        prop = await make_property_model(db, manager_id=owner.id)
        doc = await make_document_model(db, property_id=prop.id)
        token = await login(client, "outsider")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    async def test_returns_503_when_storage_upload_fails(self, client, db):
        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc = await make_document_model(db)
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(
            raise_on_put=Exception("storage is down")
        )

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 503

    async def test_returns_403_for_regular_user(self, client, db):
        await make_user_model(db, username="user1", email="user1@example.com", role=UserRole.USER)
        token = await login(client, "user1")
        doc = await make_document_model(db)

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    async def test_replace_file_returns_404_when_service_returns_none(self, client, db):

        await make_admin_model(db)
        token = await login(client, "adminuser")
        doc_id = uuid.uuid4()

        mock_service = AsyncMock()
        mock_service.build_object_url = MagicMock(return_value="http://example.com/new.pdf")
        mock_service.replace_document_file.return_value = None
        app.dependency_overrides[get_document_service] = lambda: mock_service
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc_id}/file",
            files={"file": ("new.pdf", b"content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_headers(token),
        )
        assert response.status_code == 404
