from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.document_service import DocumentService
from app.schemas.document import DocumentCreate
from app.services.exceptions import DocumentUploadError

from tests.factories import make_admin


async def test_create_document_without_storage_client_skips_upload(mock_db):
    class FakeRepo:
        async def create(self, db, payload):
            return "created"

    svc = DocumentService(document_repo=FakeRepo())  # type: ignore[arg-type]
    payload = DocumentCreate(file_name="a.pdf", file_type="application/pdf")

    result = await svc.create_document(db=mock_db, payload=payload, current_user=make_admin(), storage_client=None)
    assert result == "created"


async def test_create_document_uploads_to_storage_when_file_is_provided(mock_db):
    class RecordingStorage:
        def __init__(self):
            self.calls = []
            self.removed = []

        def put_object(self, bucket, name, stream, length=None, content_type=None):
            self.calls.append(
                {
                    "bucket": bucket,
                    "name": name,
                    "length": length,
                    "content_type": content_type,
                }
            )

        def remove_object(self, bucket, name):
            self.removed.append(
                {
                    "bucket": bucket,
                    "name": name,
                }
            )

    class FakeRepo:
        async def create(self, db, payload):
            data = payload.model_dump() if hasattr(payload, "model_dump") else payload
            return SimpleNamespace(
                id=data.get("id", uuid4()),
                file_name=data["file_name"],
                file_type=data["file_type"],
                contract_id=data.get("contract_id"),
                property_id=data.get("property_id"),
                tenant_id=data.get("tenant_id"),
            )

    storage = RecordingStorage()
    svc = DocumentService(document_repo=FakeRepo())  # type: ignore[arg-type]
    payload = DocumentCreate(file_name="a.pdf", file_type="application/pdf")
    file_obj = SimpleNamespace(content_type="application/pdf", file=BytesIO(b"%PDF-1.4 hello"))

    result = await svc.create_document(
        db=mock_db,
        payload=payload,
        current_user=make_admin(),
        storage_client=storage,
        file_obj=file_obj,
    )

    print(type(result))
    assert result.file_name == "a.pdf"
    assert len(storage.calls) == 1
    assert storage.calls[0]["name"].endswith("_a.pdf")
    assert storage.calls[0]["name"].startswith("documents/")


async def test_create_document_translates_storage_failures(mock_db):
    class FailingStorage:
        def put_object(self, bucket, name, stream, length=None, content_type=None):
            raise RuntimeError("Network Error")

    svc = DocumentService(document_repo=SimpleNamespace())  # type: ignore[arg-type]
    payload = DocumentCreate(file_name="a.pdf", file_type="application/pdf")
    file_obj = SimpleNamespace(content_type="application/pdf", file=BytesIO(b"%PDF-1.4 hello"))

    with pytest.raises(DocumentUploadError):
        await svc.create_document(
            db=mock_db,
            payload=payload,
            current_user=make_admin(),
            storage_client=FailingStorage(),
            file_obj=file_obj,
        )


async def test_delete_document_skips_storage_cleanup_when_no_storage_client_is_provided(mock_db):
    class FakeRepo:
        async def get_by_id(self, db, id):
            return SimpleNamespace(id=id, file_name="a.pdf", property_id=None, contract_id=None, tenant_id=None)

        async def delete(self, db, id):
            return SimpleNamespace(id=id, file_name="a.pdf")

    svc = DocumentService(document_repo=FakeRepo())  # type: ignore[arg-type]

    result = await svc.delete_document(db=mock_db, doc_id=uuid4(), current_user=make_admin(), storage_client=None)

    assert result is not None


async def test_delete_document_succeeds_even_when_storage_delete_fails(mock_db):
    class FailingStorage:
        def remove_object(self, bucket, name):
            raise RuntimeError("Network error")

    class FakeRepo:
        async def get_by_id(self, db, id):
            return SimpleNamespace(id=id, file_name="a.pdf", property_id=None, contract_id=None, tenant_id=None)

        async def delete(self, db, id):
            return SimpleNamespace(id=id, file_name="a.pdf")

    svc = DocumentService(document_repo=FakeRepo())  # type: ignore[arg-type]

    result = await svc.delete_document(
        db=mock_db,
        doc_id=uuid4(),
        current_user=make_admin(),
        storage_client=FailingStorage(),
    )

    assert result is not None
    mock_db.commit.assert_called_once()
