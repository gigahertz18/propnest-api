import uuid
import datetime

from app.models.user import UserRole
from tests.factories import make_admin_model, make_user_model, make_property_model, make_document_model


class TestDocumentsRoutes:
    def test_list_documents_calls_service(self, client, set_override, simple_ns):
        from app.core.dependencies import get_document_service, get_current_user

        now = datetime.datetime.utcnow()
        doc_id = uuid.uuid4()
        doc = {
            "id": doc_id,
            "file_name": "a.pdf",
            "file_type": "application/pdf",
            "file_url": "",
            "contract_id": None,
            "property_id": None,
            "tenant_id": None,
            "created_at": now,
            "updated_at": now,
        }

        set_override(get_document_service, lambda: simple_ns(list_documents=lambda db, skip, limit: [doc]))
        set_override(get_current_user, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.USER))

        response = client.get("/api/v1/documents/?skip=0&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list) and body[0]["id"] == str(doc_id)

    def test_get_document_returns_document(self, client, set_override, simple_ns):
        from app.core.dependencies import get_document_service, get_current_user

        now = datetime.datetime.utcnow()
        doc_id = uuid.uuid4()
        doc = {
            "id": doc_id,
            "file_name": "b.pdf",
            "file_type": "application/pdf",
            "file_url": "",
            "contract_id": None,
            "property_id": None,
            "tenant_id": None,
            "created_at": now,
            "updated_at": now,
        }

        set_override(get_document_service, lambda: simple_ns(get_document=lambda db, id: doc))
        set_override(get_current_user, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.USER))

        response = client.get(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(doc_id)

    def test_create_document_manager_forbidden(self, client, set_override, simple_ns):
        from app.core.dependencies import get_property_service, get_document_service, require_manager_or_above

        prop_id = uuid.uuid4()
        # Property owned by another manager
        prop = simple_ns(id=prop_id, manager_id=uuid.uuid4())

        set_override(get_property_service, lambda: simple_ns(get_property=lambda db, id: prop))
        set_override(get_document_service, lambda: simple_ns(create_document=lambda db, payload: None))
        # current user is a manager but does not own the property
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        payload = {"file_name": "a.pdf", "file_type": "application/pdf", "file_url": "", "property_id": str(prop_id)}
        response = client.post("/api/v1/documents/", json=payload)
        assert response.status_code == 403

    def test_upload_document_manager_forbidden(self, client, set_override, simple_ns):
        from app.core.dependencies import (
            get_property_service,
            get_document_service,
            require_manager_or_above,
            get_storage_client,
        )

        prop_id = uuid.uuid4()
        prop = simple_ns(id=prop_id, manager_id=uuid.uuid4())

        set_override(get_property_service, lambda: simple_ns(get_property=lambda db, id: prop))
        set_override(
            get_document_service,
            lambda: simple_ns(create_document=lambda db, payload, storage_client=None, file_obj=None: None),
        )
        set_override(get_storage_client, lambda: simple_ns())
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        files = {"file": ("test.pdf", b"data", "application/pdf")}
        data = {"file_type": "application/pdf", "property_id": str(prop_id)}
        response = client.post("/api/v1/documents/upload", files=files, data=data)
        assert response.status_code == 403

    def test_update_document_not_found_and_contract_branch_update_returns_none(self, client, set_override, simple_ns):
        from app.core.dependencies import (
            get_document_service,
            get_property_service,
            get_contract_service,
            require_manager_or_above,
        )

        doc_id = uuid.uuid4()

        # First - not found
        set_override(get_document_service, lambda: simple_ns(get_document=lambda db, id: None))
        set_override(require_manager_or_above, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER))

        response = client.patch(f"/api/v1/documents/{doc_id}", json={})
        assert response.status_code == 404

        # Second - contract branch exercised but update returns None -> 404
        contract_id = uuid.uuid4()
        property_id = uuid.uuid4()
        manager_id = uuid.uuid4()

        # document has contract_id but no property_id
        set_override(
            get_document_service,
            lambda: simple_ns(
                get_document=lambda db, id: simple_ns(contract_id=contract_id, property_id=None),
                update_document=lambda db, id, payload: None,
            ),
        )
        set_override(
            get_contract_service,
            lambda: simple_ns(
                get_contract=lambda db, id: simple_ns(property_id=property_id),
            ),
        )
        set_override(
            get_property_service,
            lambda: simple_ns(
                get_property=lambda db, id: simple_ns(manager_id=manager_id),
            ),
        )
        # manager who DOES own the property
        set_override(
            require_manager_or_above,
            lambda: simple_ns(id=manager_id, role=UserRole.MANAGER),
        )

        response = client.patch(f"/api/v1/documents/{doc_id}", json={})
        assert response.status_code == 404

    def test_delete_document_not_found_and_contract_branch_forbidden_and_delete_returns_none(
        self,
        client,
        set_override,
        simple_ns,
    ):
        from app.core.dependencies import (
            get_document_service,
            get_property_service,
            get_contract_service,
            require_manager_or_above,
        )

        doc_id = uuid.uuid4()

        # not found
        set_override(
            get_document_service,
            lambda: simple_ns(get_document=lambda db, id: None),
        )
        set_override(
            require_manager_or_above,
            lambda: simple_ns(id=uuid.uuid4(), role=UserRole.MANAGER),
        )

        response = client.delete(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 404

        # contract branch - forbidden when manager doesn't own
        contract_id = uuid.uuid4()
        property_id = uuid.uuid4()
        manager_id = uuid.uuid4()

        set_override(
            get_document_service,
            lambda: simple_ns(
                get_document=lambda db, id: simple_ns(contract_id=contract_id, property_id=None),
                delete_document=lambda db, id: False,
            ),
        )
        set_override(
            get_contract_service,
            lambda: simple_ns(
                get_contract=lambda db, id: simple_ns(property_id=property_id),
            ),
        )
        # property owned by different manager
        set_override(
            get_property_service,
            lambda: simple_ns(
                get_property=lambda db, id: simple_ns(manager_id=uuid.uuid4()),
            ),
        )
        # current user is a manager but not the owner
        set_override(
            require_manager_or_above,
            lambda: simple_ns(id=manager_id, role=UserRole.MANAGER),
        )

        response = client.delete(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 403

        # Now allow delete but underlying service reports not found -> 404
        set_override(
            get_property_service,
            lambda: simple_ns(
                get_property=lambda db, id: simple_ns(manager_id=manager_id),
            ),
        )
        response = client.delete(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 404

    def test_get_document_not_found_404(self, client, set_override, simple_ns):
        """Ensure GET /documents/{id} raises 404 when service returns None."""
        from app.core.dependencies import get_document_service, get_current_user

        set_override(
            get_document_service,
            lambda: simple_ns(get_document=lambda db, id: None),
        )
        set_override(get_current_user, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.USER))

        response = client.get(f"/api/v1/documents/{uuid.uuid4()}")
        assert response.status_code == 404


class TestDocumentsUpload:
    class DummyStorageClient:
        def __init__(self):
            self.calls = []

        def put_object(self, bucket, name, stream, length=None, content_type=None):
            data = stream.read()
            self.calls.append(
                {"bucket": bucket, "name": name, "data": data, "length": length, "content_type": content_type}
            )

    def test_documents_upload_streams_to_storage(self, client, db, set_override):
        """Integration-style test of the `/documents/upload` endpoint using a stubbed storage client."""
        from app.core.dependencies import get_current_user, get_storage_client

        admin = make_admin_model(db)
        storage = self.DummyStorageClient()

        # Override dependencies for the test
        set_override(
            get_current_user,
            lambda: admin,
        )
        set_override(
            get_storage_client,
            lambda: storage,
        )

        files = {"file": ("upload.pdf", b"PDF-BYTES", "application/pdf")}
        data = {"file_type": "application/pdf"}

        response = client.post("/api/v1/documents/upload", files=files, data=data)
        assert response.status_code == 201

        # Storage client should have received the uploaded bytes
        assert len(storage.calls) == 1
        call = storage.calls[0]
        assert call["name"] == "upload.pdf"
        assert call["data"] == b"PDF-BYTES"


class TestDocumentsUploadStreaming:
    def test_documents_upload_route_streams_file_to_storage(self, client, db, set_override):
        """POST /documents/upload should stream file to storage and return 201."""
        from app.core.dependencies import get_current_user, get_storage_client

        class RecordingStorage:
            def __init__(self):
                self.calls = []

            def put_object(self, bucket, name, stream, length=None, content_type=None, **kwargs):
                self.calls.append(
                    {"bucket": bucket, "name": name, "stream": stream, "length": length, "content_type": content_type}
                )

        storage = RecordingStorage()
        admin = make_admin_model(db)

        # Override dependencies to inject fake storage and authenticated user
        set_override(get_storage_client, lambda: storage)
        set_override(get_current_user, lambda: admin)

        files = {"file": ("upload.pdf", b"pdf-bytes", "application/pdf")}
        data = {"file_type": "application/pdf"}

        response = client.post("/api/v1/documents/upload", files=files, data=data)
        assert response.status_code == 201
        assert len(storage.calls) == 1
        assert storage.calls[0]["name"] == "upload.pdf"
        assert response.json()["file_name"] == "upload.pdf"


class TestDocumentsResourceAuth:
    def test_manager_cannot_update_and_delete_document_for_unmanaged_property(self, client, db, set_override):
        """Managers may only update/delete documents for properties they manage."""
        from app.core.dependencies import get_current_user

        manager1 = make_user_model(db, username="mgr1", email="mgr1@example.com", role=UserRole.MANAGER)
        manager2 = make_user_model(db, username="mgr2", email="mgr2@example.com", role=UserRole.MANAGER)

        # Property is assigned to manager2
        prop = make_property_model(db, manager_id=manager2.id)

        # Document attached to that property
        doc = make_document_model(db, property_id=prop.id)

        # Request as manager1 -> forbidden
        set_override(get_current_user, lambda: manager1)

        update_payload = {"file_name": "updated_name.pdf"}
        response = client.patch(f"/api/v1/documents/{doc.id}", json=update_payload)
        assert response.status_code == 403

        # Reassign property to manager1 and retry -> should succeed
        prop.manager_id = manager1.id
        db.add(prop)
        db.commit()

        response = client.patch(f"/api/v1/documents/{doc.id}", json=update_payload)
        assert response.status_code == 200

        # And delete should now be allowed
        response = client.delete(f"/api/v1/documents/{doc.id}")
        assert response.status_code == 204
