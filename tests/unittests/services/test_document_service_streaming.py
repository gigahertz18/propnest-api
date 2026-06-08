import pytest

from types import SimpleNamespace
from io import BytesIO

from app.services.document_service import DocumentService
from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate
from app.services.exceptions import DocumentUploadError


class NonSeekableIO:
    """A minimal non-seekable file-like object used by tests."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
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


class RecordingStorage:
    """Storage stub that records `put_object` calls without consuming streams."""

    def __init__(self):
        self.calls = []

    def put_object(self, bucket, name, stream, length=None, content_type=None, **kwargs):
        self.calls.append(
            {"bucket": bucket, "name": name, "stream": stream, "length": length, "content_type": content_type}
        )


class DummyStorageClient:
    """Storage stub that reads the provided stream and records the data."""

    def __init__(self):
        self.calls = []

    def put_object(self, bucket, name, stream, length=None, content_type=None):
        data = stream.read()
        self.calls.append(
            {"bucket": bucket, "name": name, "data": data, "length": length, "content_type": content_type}
        )


class ThreeArgStorage:
    """Storage stub that only supports the three-argument `put_object(bucket, name, stream)` signature."""

    def __init__(self):
        self.calls = []

    def put_object(self, bucket, name, stream):
        data = stream.read()
        self.calls.append({"bucket": bucket, "name": name, "data": data})


@pytest.fixture
def service():
    return DocumentService(document_repo=document_repo)


def make_upload(content: bytes, filename: str, content_type: str, seekable: bool = True):
    file_obj = BytesIO(content) if seekable else NonSeekableIO(content)
    return SimpleNamespace(filename=filename, content_type=content_type, file=file_obj)


def make_payload(name: str, mime: str):
    return DocumentCreate(file_name=name, file_type=mime, file_url="")


def test_streams_file_and_passes_length_and_content_type(db, service):
    content = b"%PDF-1.4 test content"
    upload = make_upload(content, "test.pdf", "application/pdf", seekable=True)
    payload = make_payload("test.pdf", "application/pdf")

    storage = RecordingStorage()

    created = service.create_document(db, payload, storage_client=storage, file_obj=upload)

    assert len(storage.calls) == 1
    call = storage.calls[0]
    assert call["name"] == "test.pdf"
    assert call["length"] == len(content)
    assert call["content_type"] == "application/pdf"
    assert created.file_name == "test.pdf"


def test_streams_file_to_storage_and_reads_content(db, service):
    content = b"PDF-DATA"
    payload = make_payload("test.pdf", "application/pdf")
    upload = make_upload(content, payload.file_name, payload.file_type)

    storage = DummyStorageClient()

    doc = service.create_document(db, payload, storage_client=storage, file_obj=upload)

    assert doc is not None
    assert len(storage.calls) == 1
    call = storage.calls[0]
    assert call["name"] == payload.file_name
    assert call["data"] == content
    assert call["content_type"] == payload.file_type


def test_rejects_disallowed_mime(db, service):
    content = b"SOME-TEXT"
    payload = make_payload("notes.txt", "text/plain")
    upload = make_upload(content, payload.file_name, payload.file_type)

    storage = DummyStorageClient()

    with pytest.raises(DocumentUploadError):
        service.create_document(db, payload, storage_client=storage, file_obj=upload)


def test_handles_non_seekable_stream(db, service):
    content = b"NON-SEEKABLE-CONTENT"
    upload = make_upload(content, "nonseek.pdf", "application/pdf", seekable=False)
    payload = make_payload("nonseek.pdf", "application/pdf")

    storage = DummyStorageClient()

    doc = service.create_document(db, payload, storage_client=storage, file_obj=upload)

    assert doc is not None
    assert len(storage.calls) == 1
    assert storage.calls[0]["data"] == content


def test_put_object_falls_back_to_three_arg_signature(db, service):
    content = b"FALLBACK-DATA"
    payload = make_payload("fallback.pdf", "application/pdf")
    upload = make_upload(content, payload.file_name, payload.file_type)

    storage = ThreeArgStorage()

    doc = service.create_document(db, payload, storage_client=storage, file_obj=upload)

    assert doc is not None
    assert len(storage.calls) == 1
    assert storage.calls[0]["data"] == content


def test_rejects_large_file_via_max_size_override(db, service):
    original_max = DocumentService._MAX_FILE_SIZE
    DocumentService._MAX_FILE_SIZE = 5

    try:
        content = b"TOO-LONG"
        payload = make_payload("big.pdf", "application/pdf")
        upload = make_upload(content, payload.file_name, payload.file_type)
        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            service.create_document(db, payload, storage_client=storage, file_obj=upload)
    finally:
        DocumentService._MAX_FILE_SIZE = original_max
