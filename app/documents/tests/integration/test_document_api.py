import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.dependencies import get_storage_client, get_document_service
from app.main import app

from app.identity.models.user import UserRole
from tests.factories import (
    make_collection_model,
    make_document,
    make_document_model,
    make_property_model,
    make_user_model,
    make_tenant_model,
    make_contract_model,
)


class FakeStorageClient:
    """Minimal stand-in for the MinIO client — only what DocumentService touches."""

    def __init__(
        self,
        raise_on_put: Exception | None = None,
        raise_on_remove: Exception | None = None,
        raise_on_get: Exception | None = None,
    ):
        self.raise_on_put = raise_on_put
        self.raise_on_remove = raise_on_remove
        self.raise_on_get = raise_on_get
        self.put_calls: list[tuple] = []
        self.remove_calls: list[tuple] = []
        self.objects: dict[str, bytes] = {}

    def put_object(self, bucket, storage_key, stream, size, content_type=None):
        if self.raise_on_put:
            raise self.raise_on_put
        self.put_calls.append(((bucket, storage_key, stream, size), {"content_type": content_type}))
        self.objects[storage_key] = stream.read()

    def get_object(self, bucket, storage_key):
        if self.raise_on_get:
            raise self.raise_on_get

        data = self.objects[storage_key]

        class _Response:
            def read(self_inner):
                return data

            def close(self_inner):
                pass

            def release_conn(self_inner):
                pass

        return _Response()

    def remove_object(self, *args, **kwargs):
        if self.raise_on_remove:
            raise self.raise_on_remove
        self.remove_calls.append((args, kwargs))


# ─── GET /documents/ ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListDocumentsRoute:
    async def test_returns_empty_list(self, client, authenticate_manager):
        auth_ctx = await authenticate_manager()
        response = await client.get("/api/v1/documents/", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_admin_sees_all_documents(self, client, db, authenticate_admin):
        await make_document_model(db, file_name="a.pdf")
        await make_document_model(db, file_name="b.pdf")

        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/documents/", headers=auth_ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 2

    async def test_admin_sees_all_documents_with_pagination(self, client, db, authenticate_admin):
        await make_document_model(db, file_name="a.pdf")
        await make_document_model(db, file_name="b.pdf")

        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/documents/?skip=1&limit=1", headers=auth_ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 1

    async def test_manager_sees_only_documents_for_own_properties(self, client, db, authenticate_manager):
        auth_ctx = await authenticate_manager()
        other_manager = await authenticate_manager(username="othermgr", email="othermgr@example.com")
        own_prop = await make_property_model(db, manager_id=auth_ctx.user.id)
        other_prop = await make_property_model(db, manager_id=other_manager.user.id)

        owned_doc = await make_document_model(db, file_name="mine.pdf", property_id=own_prop.id)
        await make_document_model(db, file_name="not_mine.pdf", property_id=other_prop.id)

        response = await client.get("/api/v1/documents/", headers=auth_ctx.headers)
        assert response.status_code == 200
        ids = {d["id"] for d in response.json()["items"]}
        assert ids == {str(owned_doc.id)}

    async def test_regular_user_cannot_list_documents(self, client, authenticate_user):
        auth_ctx = await authenticate_user()
        response = await client.get("/api/v1/documents/", headers=auth_ctx.headers)
        assert response.status_code == 403

    async def test_unauthenticated_cannot_list_documents(self, client):
        response = await client.get("/api/v1/documents/")
        assert response.status_code == 403


# ─── GET /documents/{id} ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetDocumentRoute:
    async def test_admin_can_get_any_document(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db)
        response = await client.get(f"/api/v1/documents/{doc.id}", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(doc.id)

    async def test_manager_can_get_document_for_own_property(self, client, db, authenticate_manager):
        auth_ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=auth_ctx.user.id)
        doc = await make_document_model(db, property_id=prop.id)
        response = await client.get(f"/api/v1/documents/{doc.id}", headers=auth_ctx.headers)
        assert response.status_code == 200

    async def test_manager_cannot_get_document_for_another_managers_property(self, client, db, authenticate_manager):
        auth_ctx = await authenticate_manager()
        other_manager = await make_user_model(
            db, username="othermgr", email="othermgr@example.com", role=UserRole.MANAGER
        )
        prop = await make_property_model(db, manager_id=other_manager.id)
        doc = await make_document_model(db, property_id=prop.id)
        response = await client.get(f"/api/v1/documents/{doc.id}", headers=auth_ctx.headers)
        assert response.status_code == 403

    async def test_regular_user_cannot_get_document(self, client, db, authenticate_user):
        auth_ctx = await authenticate_user()
        doc = await make_document_model(db)
        response = await client.get(f"/api/v1/documents/{doc.id}", headers=auth_ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_not_found(self, client, authenticate_manager):
        auth_ctx = await authenticate_manager()
        response = await client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


# ─── POST /documents/ (JSON metadata-only create) ────────────────────────────


@pytest.mark.asyncio
class TestCreateDocumentRoute:
    async def test_creates_document_successfully(self, client, db, authenticate_admin):

        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        payload = make_document(file_name="new.pdf")
        payload["contract_id"] = None
        payload["property_id"] = str(prop.id)
        payload["tenant_id"] = None
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 201
        data = response.json()
        assert data["file_name"] == "new.pdf"
        assert data["id"] is not None

    async def test_returns_422_when_file_name_missing(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        payload = make_document()
        del payload["file_name"]
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 422

    async def test_returns_403_for_regular_user(self, client, authenticate_user):

        auth_ctx = await authenticate_user()
        payload = make_document()
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 403

    async def test_manager_can_create_for_their_own_property(self, client, db, authenticate_manager):

        auth_ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=auth_ctx.user.id)
        payload = make_document(property_id=str(prop.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 201

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db, authenticate_manager):

        owner_ctx = await authenticate_manager(
            username="owner",
            email="owner@example.com",
        )
        outsider_ctx = await authenticate_manager(
            username="outsider",
            email="outsider@example.com",
        )
        prop = await make_property_model(db, manager_id=owner_ctx.user.id)
        payload = make_document(property_id=str(prop.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=outsider_ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_property_not_found(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        payload = make_document(property_id=str(uuid.uuid4()))

        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 404

    async def test_returns_400_when_property_does_not_match_contract(self, client, db, authenticate_admin):
        """Regression test: a payload that supplies both a contract_id and a
        property_id that don't belong to each other must be rejected with a
        client error, not silently accepted against the (unrelated) owned
        property, and not surfaced as an unhandled 500."""
        auth_ctx = await authenticate_admin()
        tenant = await make_tenant_model(db)
        contract_property = await make_property_model(db)
        unrelated_property = await make_property_model(db)
        contract = await make_contract_model(db, property_id=contract_property.id, tenant_id=tenant.id)

        payload = make_document(contract_id=str(contract.id), property_id=str(unrelated_property.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 400

    async def test_returns_400_when_tenant_does_not_match_contract(self, client, db, authenticate_admin):
        """Same as above, but for a mismatched tenant_id supplied alongside contract_id."""
        auth_ctx = await authenticate_admin()
        tenant = await make_tenant_model(db)
        unrelated_tenant = await make_tenant_model(db, email="unrelated@example.com")
        prop = await make_property_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)

        payload = make_document(contract_id=str(contract.id), tenant_id=str(unrelated_tenant.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 400

    async def test_creates_document_without_file_url(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()

        payload = {
            "file_name": "lease.pdf",
            "file_type": "application/pdf",
            "property_id": None,
            "contract_id": None,
            "tenant_id": None,
        }

        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 201
        data = response.json()

        assert data["file_name"] == "lease.pdf"
        assert data["file_type"] == "application/pdf"
        assert data["file_url"]
        assert "/documents/" in data["file_url"]


# ─── collection_id linking ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateDocumentRouteCollectionLinking:
    async def test_creates_document_linked_to_collection_on_same_property(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        collection = await make_collection_model(db, property_id=prop.id)

        payload = make_document(property_id=str(prop.id), collection_id=str(collection.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 201
        assert response.json()["collection_id"] == str(collection.id)

    async def test_returns_404_when_collection_not_found(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)

        payload = make_document(property_id=str(prop.id), collection_id=str(uuid.uuid4()))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 404

    async def test_collection_id_is_optional(self, client, db, authenticate_admin):
        """Regression: creating a document without collection_id still works."""
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)

        payload = make_document(property_id=str(prop.id))
        response = await client.post("/api/v1/documents/", json=payload, headers=auth_ctx.headers)

        assert response.status_code == 201
        assert response.json()["collection_id"] is None


# ─── POST /documents/upload (multipart upload) ───────────────────────────────


@pytest.mark.asyncio
class TestUploadDocumentRoute:
    async def test_uploads_document_successfully(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["file_name"] == "upload.pdf"

    async def test_returns_503_when_storage_upload_fails(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(
            raise_on_put=Exception("storage is down")
        )

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 503

    async def test_returns_422_when_filename_missing(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 422

    async def test_returns_404_when_property_not_found(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf", "property_id": str(uuid.uuid4())},
            headers=auth_ctx.headers,
        )

        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db, authenticate_manager):
        owner_ctx = await authenticate_manager(
            username="owner",
            email="owner@example.com",
        )
        outsider_ctx = await authenticate_manager(
            username="outsider",
            email="outsider@example.com",
        )
        prop = await make_property_model(db, manager_id=owner_ctx.user.id)

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf", "property_id": str(prop.id)},
            headers=outsider_ctx.headers,
        )
        assert response.status_code == 403

    async def test_returns_403_for_regular_user(self, client, authenticate_user):
        auth_ctx = await authenticate_user()
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 403

    async def test_same_filename_uploads_use_distinct_storage_keys(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()

        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        response1 = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 first", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )

        response2 = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 second", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )

        assert response1.status_code == 201
        assert response2.status_code == 201

        first_key = storage.put_calls[0][0][1]
        second_key = storage.put_calls[1][0][1]

        assert first_key != second_key

        assert first_key.endswith("_lease.pdf")
        assert second_key.endswith("_lease.pdf")

    async def test_returns_400_when_property_does_not_match_contract(self, client, db, authenticate_admin):
        """Regression test: uploading with a contract_id and a property_id
        that don't belong to each other must be rejected, not silently
        accepted against the unrelated property."""
        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        tenant = await make_tenant_model(db)
        contract_property = await make_property_model(db)
        unrelated_property = await make_property_model(db)
        contract = await make_contract_model(db, property_id=contract_property.id, tenant_id=tenant.id)

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("upload.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={
                "file_type": "application/pdf",
                "contract_id": str(contract.id),
                "property_id": str(unrelated_property.id),
            },
            headers=auth_ctx.headers,
        )

        assert response.status_code == 400


# ─── PATCH /documents/{id} ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateDocumentRoute:
    async def test_relink_to_different_property(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        new_prop = await make_property_model(db)
        doc = await make_document_model(db, file_name="old.pdf", property_id=prop.id)
        response = await client.patch(
            f"/api/v1/documents/{doc.id}",
            json={"property_id": str(new_prop.id)},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 200
        assert response.json()["property_id"] == str(new_prop.id)

    async def test_returns_404_when_not_found(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        response = await client.patch(
            f"/api/v1/documents/{uuid.uuid4()}",
            json={"property_id": str(uuid.uuid4())},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db, authenticate_manager):
        owner_ctx = await authenticate_manager(username="owner", email="owner@example.com")
        outsider_ctx = await authenticate_manager(username="outsider", email="outsider@example.com")
        prop = await make_property_model(db, manager_id=owner_ctx.user.id)
        doc = await make_document_model(db, property_id=prop.id)

        response = await client.patch(
            f"/api/v1/documents/{doc.id}",
            json={"property_id": str(prop.id)},
            headers=outsider_ctx.headers,
        )
        assert response.status_code == 403

    async def test_returns_400_when_relink_property_does_not_match_contract(self, client, db, authenticate_admin):
        """Regression test: relinking a document with a contract_id and a
        property_id that don't belong to each other must be rejected."""
        auth_ctx = await authenticate_admin()
        tenant = await make_tenant_model(db)
        contract_property = await make_property_model(db)
        unrelated_property = await make_property_model(db)
        contract = await make_contract_model(db, property_id=contract_property.id, tenant_id=tenant.id)
        doc = await make_document_model(db, property_id=contract_property.id)

        response = await client.patch(
            f"/api/v1/documents/{doc.id}",
            json={"contract_id": str(contract.id), "property_id": str(unrelated_property.id)},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 400


# ─── DELETE /documents/{id} ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteDocumentRoute:
    async def test_deletes_document_successfully(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db)

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.delete(f"/api/v1/documents/{doc.id}", headers=auth_ctx.headers)
        assert response.status_code == 204
        assert response.content == b""

    async def test_deleted_document_is_gone(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db)
        document_id = doc.id

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        await client.delete(f"/api/v1/documents/{document_id}", headers=auth_ctx.headers)
        response = await client.get(f"/api/v1/documents/{document_id}", headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_404_when_not_found(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.delete(f"/api/v1/documents/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db, authenticate_manager):
        owner_ctx = await authenticate_manager(username="owner", email="owner@example.com")
        outsider_ctx = await authenticate_manager(username="outsider", email="outsider@example.com")
        prop = await make_property_model(db, manager_id=owner_ctx.user.id)
        doc = await make_document_model(db, property_id=prop.id)

        response = await client.delete(f"/api/v1/documents/{doc.id}", headers=outsider_ctx.headers)
        assert response.status_code == 403

    async def test_deletes_successfully_even_when_storage_removal_fails(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db)
        document_id = doc.id

        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(
            raise_on_remove=Exception("storage is down")
        )

        response = await client.delete(f"/api/v1/documents/{document_id}", headers=auth_ctx.headers)
        assert response.status_code == 204
        assert response.content == b""

        response = await client.get(f"/api/v1/documents/{document_id}", headers=auth_ctx.headers)
        assert response.status_code == 404


# ─── PATCH /{id}/file ───────────────────────────────────────────────────
@pytest.mark.asyncio
class TestReplaceDocumentFileRoute:
    async def test_replaces_file_successfully(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db, file_name="old.pdf")
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 new content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 200
        assert response.json()["file_name"] == "new.pdf"

    async def test_returns_422_when_filename_missing(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db)
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("", b"%PDF-1.4 content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert (
            response.status_code == 422
        )  # FastAPI validates this before your 400 check fires — verify which actually wins

    async def test_returns_404_when_document_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{uuid.uuid4()}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized(self, client, db, authenticate_manager):
        owner_ctx = await authenticate_manager(username="owner", email="owner@example.com")
        outsider_ctx = await authenticate_manager(username="outsider", email="outsider@example.com")

        prop = await make_property_model(db, manager_id=owner_ctx.user.id)
        doc = await make_document_model(db, property_id=prop.id)
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=outsider_ctx.headers,
        )
        assert response.status_code == 403

    async def test_returns_503_when_storage_upload_fails(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db)
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(
            raise_on_put=Exception("storage is down")
        )

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 503

    async def test_returns_403_for_regular_user(self, client, db, authenticate_user):
        auth_ctx = await authenticate_user()
        doc = await make_document_model(db)

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 403

    async def test_replace_file_returns_404_when_service_returns_none(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        doc_id = uuid.uuid4()

        mock_service = AsyncMock()
        mock_service.build_object_url = MagicMock(return_value="http://example.com/new.pdf")
        mock_service.replace_document_file.return_value = None
        app.dependency_overrides[get_document_service] = lambda: mock_service
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        response = await client.put(
            f"/api/v1/documents/{doc_id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 404

    async def test_returns_400_when_relink_property_does_not_match_contract(self, client, db, authenticate_admin):
        """Regression test: replacing a document's file while relinking it
        with a contract_id and a property_id that don't belong to each
        other must be rejected."""
        auth_ctx = await authenticate_admin()
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()

        tenant = await make_tenant_model(db)
        contract_property = await make_property_model(db)
        unrelated_property = await make_property_model(db)
        contract = await make_contract_model(db, property_id=contract_property.id, tenant_id=tenant.id)
        doc = await make_document_model(db, property_id=contract_property.id)

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 content", "application/pdf")},
            data={
                "file_type": "application/pdf",
                "contract_id": str(contract.id),
                "property_id": str(unrelated_property.id),
            },
            headers=auth_ctx.headers,
        )
        assert response.status_code == 400

    async def test_returns_500_with_generic_detail_when_promotion_leaves_storage_inconsistent(
        self, client, db, authenticate_admin
    ):
        """The DB commit succeeds, but promoting the staged upload to its
        canonical key afterward fails — DocumentService deliberately lets
        DocumentStorageInconsistentError escape uncaught here (see
        replace_document_file's docstring), so this must be the global
        ServiceException handler's generic 500, not a raw unhandled crash
        and not str(exc) (which could leak internal storage error text)."""
        auth_ctx = await authenticate_admin()
        doc = await make_document_model(db, file_name="original.pdf")

        class FailsOnSecondPut(FakeStorageClient):
            def __init__(self):
                super().__init__()
                self._puts = 0

            def put_object(self, *args, **kwargs):
                self._puts += 1
                if self._puts >= 2:
                    raise RuntimeError("MinIO blip")
                super().put_object(*args, **kwargs)

        app.dependency_overrides[get_storage_client] = lambda: FailsOnSecondPut()

        response = await client.put(
            f"/api/v1/documents/{doc.id}/file",
            files={"file": ("new.pdf", b"%PDF-1.4 new content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "An unexpected error occurred while processing this request."}


# ─── GET /documents/{document_id}/download ────────────────────────────────────


@pytest.mark.asyncio
class TestDownloadDocumentRoute:
    async def test_admin_can_download_any_document(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        document_id = upload.json()["id"]

        response = await client.get(f"/api/v1/documents/{document_id}/download", headers=auth_ctx.headers)

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]
        assert response.content == b"%PDF-1.4 fake content"

    async def test_manager_can_download_document_for_owned_property(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf", "property_id": str(prop.id)},
            headers=mgr_ctx.headers,
        )
        document_id = upload.json()["id"]

        response = await client.get(f"/api/v1/documents/{document_id}/download", headers=mgr_ctx.headers)
        assert response.status_code == 200

    async def test_returns_403_for_manager_not_owning_the_property(
        self, client, db, authenticate_manager, authenticate_admin
    ):
        admin_ctx = await authenticate_admin()
        mgr = await make_user_model(db, username="dlmgr-owner", email="dlmgr-owner@example.com", role=UserRole.MANAGER)
        prop = await make_property_model(db, manager_id=mgr.id)
        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf", "property_id": str(prop.id)},
            headers=admin_ctx.headers,
        )
        document_id = upload.json()["id"]

        outsider_ctx = await authenticate_manager(username="dlmgr-other", email="dlmgr-other@example.com")
        response = await client.get(f"/api/v1/documents/{document_id}/download", headers=outsider_ctx.headers)
        assert response.status_code == 403

    async def test_returns_403_for_regular_user(self, client, authenticate_admin, authenticate_user):
        auth_ctx = await authenticate_admin()
        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        document_id = upload.json()["id"]

        user_ctx = await authenticate_user()
        response = await client.get(f"/api/v1/documents/{document_id}/download", headers=user_ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_for_unknown_document(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/documents/{uuid.uuid4()}/download", headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_500_when_object_missing_from_storage(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        document_id = upload.json()["id"]

        storage.objects.clear()  # simulate the object having disappeared from storage
        response = await client.get(f"/api/v1/documents/{document_id}/download", headers=auth_ctx.headers)
        assert response.status_code == 500

    async def test_get_document_metadata_route_unaffected(self, client, authenticate_admin):
        """Regression: the existing metadata route still works after adding /download."""
        auth_ctx = await authenticate_admin()
        storage = FakeStorageClient()
        app.dependency_overrides[get_storage_client] = lambda: storage

        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("lease.pdf", b"%PDF-1.4 fake content", "application/pdf")},
            data={"file_type": "application/pdf"},
            headers=auth_ctx.headers,
        )
        document_id = upload.json()["id"]

        response = await client.get(f"/api/v1/documents/{document_id}", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == document_id
