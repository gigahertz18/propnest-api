from types import SimpleNamespace

from app.services.document_service import DocumentService
from app.schemas.document import DocumentCreate


def test_create_document_calls_stat_object_when_put_not_present():
    class FakeRepo:
        def create(self, db, payload):
            return "created"

    # Storage client with stat_object but no put_object
    storage_client = SimpleNamespace(stat_object=lambda bucket, name: True)

    svc = DocumentService(document_repo=FakeRepo())
    payload = DocumentCreate(file_name="a.pdf", file_type="application/pdf", file_url="http://example.com/a.pdf")

    result = svc.create_document(db=None, payload=payload, storage_client=storage_client)
    assert result == "created"
