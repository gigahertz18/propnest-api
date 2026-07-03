import datetime
import pytest
import uuid

from unittest.mock import AsyncMock

from app.models.user import UserRole
from app.core.dependencies import get_document_service, get_current_user, get_property_service, require_manager_or_above, get_storage_client, get_contract_service
from tests.factories import make_admin_model, make_user_model, make_property_model, make_document_model


@pytest.mark.asyncio
class TestDocumentsRoutes:
    async def test_list_documents_calls_service(self, client, set_override, simple_ns):

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

        set_override(get_document_service, lambda: simple_ns(list_documents=AsyncMock(return_value=[doc])))
        set_override(get_current_user, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.USER))

        response = await client.get("/api/v1/documents/?skip=0&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list) and body[0]["id"] == str(doc_id)

    async def test_get_document_returns_document(self, client, set_override, simple_ns):

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

        set_override(get_document_service, lambda: simple_ns(get_document=AsyncMock(return_value=doc)))
        set_override(get_current_user, lambda: simple_ns(id=uuid.uuid4(), role=UserRole.USER))

        response = await client.get(f"/api/v1/documents/{doc_id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(doc_id)
