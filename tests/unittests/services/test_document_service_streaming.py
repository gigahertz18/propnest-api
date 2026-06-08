from types import SimpleNamespace
from io import BytesIO

from app.services.document_service import DocumentService
from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate
from tests.factories import make_document


def test_document_service_streams_file_and_passes_length_and_content_type(db):
    """Ensure `DocumentService.create_document` streams file-like objects to storage."""

    class RecordingStorage:
        def __init__(self):
            self.calls = []

        def put_object(self, bucket, name, stream, length=None, content_type=None, **kwargs):
            # Record the call without consuming the stream
            self.calls.append({"bucket": bucket, "name": name, "stream": stream, "length": length, "content_type": content_type})

    storage = RecordingStorage()
    svc = DocumentService(document_repo=document_repo)

    data = b"%PDF-1.4 test content"
    fake_upload = SimpleNamespace(file=BytesIO(data), filename="test.pdf", content_type="application/pdf")
    payload = DocumentCreate(file_name="test.pdf", file_type="application/pdf", file_url="")

    created = svc.create_document(db, payload, storage_client=storage, file_obj=fake_upload)

    assert len(storage.calls) == 1
    call = storage.calls[0]
    assert call["name"] == "test.pdf"
    assert call["length"] == len(data)
    assert call["content_type"] == "application/pdf"
    assert created.file_name == "test.pdf"
import io

import pytest

from types import SimpleNamespace

from app.services.document_service import DocumentService
from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate
from app.services.exceptions import DocumentUploadError


class DummyStorageClient:
    def __init__(self):
        self.calls = []

    def put_object(self, bucket, name, stream, length=None, content_type=None):
        # Read the stream to verify content
        data = stream.read()
        self.calls.append({"bucket": bucket, "name": name, "data": data, "length": length, "content_type": content_type})


def test_create_document_streams_file_to_storage(db):
    service = DocumentService(document_repo=document_repo)

    content = b"PDF-DATA"
    payload = DocumentCreate(file_name="test.pdf", file_type="application/pdf", file_url="")

    # Simulate an UploadFile-like object with a seekable BytesIO
    fake_upload = SimpleNamespace(filename=payload.file_name, content_type=payload.file_type, file=io.BytesIO(content))

    storage = DummyStorageClient()

    doc = service.create_document(db, payload, storage_client=storage, file_obj=fake_upload)

    assert doc is not None
    # Storage client should have been called once and received the expected content
    assert len(storage.calls) == 1
    call = storage.calls[0]
    assert call["name"] == payload.file_name
    assert call["data"] == content
    assert call["content_type"] == payload.file_type


def test_create_document_rejects_disallowed_mime(db):
    service = DocumentService(document_repo=document_repo)

    content = b"SOME-TEXT"
    payload = DocumentCreate(file_name="notes.txt", file_type="text/plain", file_url="")

    fake_upload = SimpleNamespace(filename=payload.file_name, content_type=payload.file_type, file=io.BytesIO(content))

    storage = DummyStorageClient()

    with pytest.raises(DocumentUploadError):
        service.create_document(db, payload, storage_client=storage, file_obj=fake_upload)


def test_create_document_handles_non_seekable_stream(db):
    service = DocumentService(document_repo=document_repo)

    content = b"NON-SEEKABLE-CONTENT"

    class NonSeekable:
        def __init__(self, data):
            self._data = data
            self._pos = 0

        def read(self, n=-1):
            if n == -1:
                r = self._data[self._pos :]
                self._pos = len(self._data)
                return r
            r = self._data[self._pos : self._pos + n]
            self._pos += len(r)
            return r

        def tell(self):
            raise OSError("non-seekable")

        def seek(self, *args, **kwargs):
            raise OSError("non-seekable")

    fake_upload = SimpleNamespace(filename="nonseek.pdf", content_type="application/pdf", file=NonSeekable(content))
    payload = DocumentCreate(file_name="nonseek.pdf", file_type="application/pdf", file_url="")

    storage = DummyStorageClient()

    doc = service.create_document(db, payload, storage_client=storage, file_obj=fake_upload)

    assert doc is not None
    assert len(storage.calls) == 1
    assert storage.calls[0]["data"] == content


def test_put_object_falls_back_to_three_arg_signature(db):
    service = DocumentService(document_repo=document_repo)

    content = b"FALLBACK-DATA"
    payload = DocumentCreate(file_name="fallback.pdf", file_type="application/pdf", file_url="")
    fake_upload = SimpleNamespace(filename=payload.file_name, content_type=payload.file_type, file=BytesIO(content))

    class ThreeArgStorage:
        def __init__(self):
            self.calls = []

        def put_object(self, bucket, name, stream):
            data = stream.read()
            self.calls.append({"bucket": bucket, "name": name, "data": data})

    storage = ThreeArgStorage()

    doc = service.create_document(db, payload, storage_client=storage, file_obj=fake_upload)

    assert doc is not None
    assert len(storage.calls) == 1
    assert storage.calls[0]["data"] == content


def test_create_document_rejects_large_file_via_max_size_override(db):
    service = DocumentService(document_repo=document_repo)

    # Temporarily lower the max size to avoid allocating huge buffers in tests
    original_max = DocumentService._MAX_FILE_SIZE
    DocumentService._MAX_FILE_SIZE = 5

    try:
        content = b"TOO-LONG"
        payload = DocumentCreate(file_name="big.pdf", file_type="application/pdf", file_url="")
        fake_upload = SimpleNamespace(filename=payload.file_name, content_type=payload.file_type, file=BytesIO(content))
        storage = DummyStorageClient()

        import pytest

        with pytest.raises(DocumentUploadError):
            service.create_document(db, payload, storage_client=storage, file_obj=fake_upload)
    finally:
        DocumentService._MAX_FILE_SIZE = original_max
