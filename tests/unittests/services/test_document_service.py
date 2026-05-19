import pytest

from types import SimpleNamespace

from app.services.document_service import DocumentService
from app.services.exceptions import DocumentUploadError
from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate
from tests.factories import make_document_model, make_document


def test_document_service_translates_storage_failures(db):
    # Create a minimal fake storage client that raises on put_object
    class FailingStorage:
        def put_object(self, *args, **kwargs):
            raise RuntimeError("network error")

    # Use real repo to avoid mocking DB behavior
    doc_service = DocumentService(document_repo=document_repo)

    payload = DocumentCreate(**make_document())

    with pytest.raises(DocumentUploadError):
        doc_service.create_document(db, payload, storage_client=FailingStorage())
