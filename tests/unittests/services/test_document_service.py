import pytest

from io import BytesIO
from types import SimpleNamespace

from app.services.document_service import DocumentService
from app.services.exceptions import DocumentUploadError
from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate
from tests.factories import make_document


async def test_document_service_translate_storage_failures(db):
    """
    Storage failures during upload must surface as DocumentUploadError.
    file_obj is required - without it, no upload is attempted.
    """

    class FailingStorage:
        def put_object(self, bucket, name, stream, length=None, content_type=None):
            raise RuntimeError("Network Error")

    doc_service = DocumentService(document_repo=document_repo)

    payload = DocumentCreate(**make_document())

    # provide minimal file_obj so the upload path is actually entered
    file_obj = SimpleNamespace(content_type="application/pdf", file=BytesIO(b"fake pdf content"))

    with pytest.raises(DocumentUploadError):
        await doc_service.create_document(
            db,
            payload,
            storage_client=FailingStorage(),
            file_obj=file_obj,
        )
