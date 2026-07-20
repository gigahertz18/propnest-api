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

    def put_object(self, bucket, name, stream, length=None, content_type=None):
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


@pytest.mark.asyncio
class TestUploadStreaming:
    """Streaming/upload behavior of DocumentService.create_document: length
    and content-type propagation, non-seekable streams, storage-client
    signature compatibility, and the size limit."""

    async def test_streams_file_and_passes_length_and_content_type(self, db, service):
        content = b"%PDF-1.4 test content"
        upload = make_upload(content, "test.pdf", "application/pdf", seekable=True)
        payload = make_payload("test.pdf", "application/pdf")

        storage = RecordingStorage()

        created = await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert len(storage.calls) == 1
        call = storage.calls[0]
        assert call["name"].endswith("_test.pdf")
        assert call["length"] == len(content)
        assert call["content_type"] == "application/pdf"
        assert created.file_name == "test.pdf"

    async def test_streams_file_to_storage_and_reads_content(self, db, service):
        content = b"%PDF-1.4 PDF-DATA"
        payload = make_payload("test.pdf", "application/pdf")
        upload = make_upload(content, payload.file_name, payload.file_type)

        storage = DummyStorageClient()

        doc = await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert doc is not None
        assert len(storage.calls) == 1
        call = storage.calls[0]
        assert call["name"].endswith(f"_{payload.file_name}")
        assert call["data"] == content
        assert call["content_type"] == payload.file_type

    async def test_rejects_disallowed_mime(self, db, service):
        content = b"SOME-TEXT"
        payload = make_payload("notes.txt", "text/plain")
        upload = make_upload(content, payload.file_name, payload.file_type)

        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            await service.create_document(db, payload, storage_client=storage, file_obj=upload)

    async def test_handles_non_seekable_stream(self, db, service):
        content = b"%PDF-1.4 NON-SEEKABLE-CONTENT"
        upload = make_upload(content, "nonseek.pdf", "application/pdf", seekable=False)
        payload = make_payload("nonseek.pdf", "application/pdf")

        storage = DummyStorageClient()

        doc = await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert doc is not None
        assert len(storage.calls) == 1
        assert storage.calls[0]["data"] == content

    async def test_put_object_called_with_correct_signature(self, db, service):
        """
        Replaces test_put_object_falls_back_to_three_arg_signature.
        Verifies put_object is called with the full correct signature,
        not a degraded fallback.
        """
        content = b"%PDF-1.4 FALLBACK-DATA"
        payload = make_payload("fallback.pdf", "application/pdf")
        upload = make_upload(content, payload.file_name, payload.file_type)

        storage = ThreeArgStorage()

        doc = await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert doc is not None
        assert len(storage.calls) == 1
        assert storage.calls[0]["data"] == content

    async def test_rejects_large_file_via_max_size_override(self, db, service):
        original_max = DocumentService._MAX_FILE_SIZE
        DocumentService._MAX_FILE_SIZE = 5

        try:
            content = b"TOO-LONG"
            payload = make_payload("big.pdf", "application/pdf")
            upload = make_upload(content, payload.file_name, payload.file_type)
            storage = DummyStorageClient()

            with pytest.raises(DocumentUploadError):
                await service.create_document(db, payload, storage_client=storage, file_obj=upload)
        finally:
            DocumentService._MAX_FILE_SIZE = original_max


# ─── MIME sniffing ──────────────────────────────────────────────────────
# Real, minimal signatures for each allowed type. Validation must be based
# on these bytes alone — never on file_obj.content_type or payload.file_type,
# both of which are attacker-controlled request metadata.
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16
DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16  # legacy .doc (OLE)
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 16  # .docx (OOXML/zip)
EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00"  # disallowed: PE header
PLAIN_BYTES = b"just some plain text, not a real document at all"


@pytest.mark.asyncio
class TestMimeSniffing:
    """_upload_to_storage must validate against the file's actual magic
    bytes/signature, never against file_obj.content_type or
    payload.file_type — both are attacker-controlled request metadata."""

    @pytest.mark.parametrize(
        "content, filename, expected_content_type",
        [
            (PDF_BYTES, "a.pdf", "application/pdf"),
            (PNG_BYTES, "a.png", "image/png"),
            (JPEG_BYTES, "a.jpg", "image/jpeg"),
            (DOC_BYTES, "a.doc", "application/msword"),
            (DOCX_BYTES, "a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ],
    )
    async def test_accepts_legitimate_file_of_each_allowed_type(
        self, db, service, content, filename, expected_content_type
    ):
        """A real file of each allowed type is accepted and stored with
        the sniffed (correct) content type."""
        payload = make_payload(filename, expected_content_type)
        upload = make_upload(content, filename, expected_content_type)
        storage = DummyStorageClient()

        await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert len(storage.calls) == 1
        assert storage.calls[0]["content_type"] == expected_content_type
        assert storage.calls[0]["data"] == content

    async def test_rejects_file_with_mismatched_extension_and_declared_type(self, db, service):
        """Client claims 'a.pdf' / application/pdf, but the bytes are
        actually a PNG. Must be rejected even though both pieces of
        client metadata claim an allowed type."""
        payload = make_payload("a.pdf", "application/pdf")
        upload = make_upload(PNG_BYTES, "a.pdf", "application/pdf")
        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            await service.create_document(db, payload, storage_client=storage, file_obj=upload)
        assert storage.calls == []

    async def test_rejects_disallowed_real_type_even_with_allowed_declared_type(self, db, service):
        """Bytes are an executable, but the client claims application/pdf
        on both the multipart content_type and the request body. Sniffing
        must catch this regardless of either claim."""
        payload = make_payload("invoice.pdf", "application/pdf")
        upload = make_upload(EXE_BYTES, "invoice.pdf", "application/pdf")
        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            await service.create_document(db, payload, storage_client=storage, file_obj=upload)
        assert storage.calls == []

    async def test_rejects_unrecognized_signature(self, db, service):
        """Plain text with no recognizable magic bytes is rejected, even
        when labeled as an allowed type."""
        payload = make_payload("notes.pdf", "application/pdf")
        upload = make_upload(PLAIN_BYTES, "notes.pdf", "application/pdf")
        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            await service.create_document(db, payload, storage_client=storage, file_obj=upload)

    async def test_rejects_legitimate_file_despite_disallowed_declared_type(self, db, service):
        """
        A genuinely valid PDF, but declared as 'application/octet-stream' on both multipart header
        and request body. Even though real bytes are safe, mismatch itself will be rejected to prevent
        mismatch between what MinIO actually stored and DB records.
        """
        content = b"%PDF-1.4 legit content"
        payload = make_payload("a.pdf", "application/octet-stream")
        upload = make_upload(content, "a.pdf", "application/octet-stream")
        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert storage.calls == []

    async def test_accepts_jpg_alias_declared_for_real_jpeg_bytes(self, db, service):
        """
        'image/jpg' and 'image/jpeg' are the same real format - the declared/sniffed match check must
        not treat this as a mismatch.
        """
        payload = make_payload("a.jpg", "image/jpg")
        upload = make_upload(JPEG_BYTES, "a.jpg", "image/jpg")

        storage = DummyStorageClient()

        await service.create_document(db, payload, storage_client=storage, file_obj=upload)

        assert len(storage.calls) == 1
        assert storage.calls[0]["content_type"] == "image/jpeg"

    async def test_ignores_content_type_when_file_obj_has_none(self, db, service):
        """Some callers may pass a file_obj with no content_type
        attribute at all, falling back to payload.file_type in the old
        code. That fallback must no longer influence validation."""
        payload = make_payload("a.pdf", "application/pdf")
        upload = SimpleNamespace(file=BytesIO(EXE_BYTES))  # no content_type attr
        storage = DummyStorageClient()

        with pytest.raises(DocumentUploadError):
            await service.create_document(db, payload, storage_client=storage, file_obj=upload)
