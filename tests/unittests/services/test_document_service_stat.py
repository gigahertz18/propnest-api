from app.services.document_service import DocumentService
from app.schemas.document import DocumentCreate


def test_create_document_without_storage_client_skips_upload():
    class FakeRepo:
        def create(self, db, payload):
            return "created"

    svc = DocumentService(document_repo=FakeRepo())
    payload = DocumentCreate(file_name="a.pdf", file_type="application/pdf", file_url="http://exaple.com/a.pdf")

    result = svc.create_document(db=None, payload=payload, storage_client=None)
    assert result == "created"
