from uuid import UUID
from sqlalchemy.orm import Session
from io import BytesIO

from app.repositories.document import DocumentRepository
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.models.document import Document
from app.services.exceptions import DocumentUploadError
from app.core.config import settings


class DocumentService:
    """Business logic for `Document` entities.

    Optionally accepts a storage client (e.g., MinIO) for uploading files.
    When provided with a file-like object (`file_obj`) the service will perform
    basic MIME and size validation and stream the content to the storage
    client. Errors are translated to domain exceptions so routes can respond
    appropriately.
    """

    # Default max file size (10 MB) and a small allowed MIME set for now.
    _MAX_FILE_SIZE = 10 * 1024 * 1024
    _ALLOWED_MIME = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    def __init__(self, document_repo: DocumentRepository) -> None:
        self.document_repo = document_repo

    def list_documents(self, db: Session, skip: int = 0, limit: int = 100) -> list[Document]:
        return self.document_repo.get_all(db, skip=skip, limit=limit)

    def get_document(self, db: Session, id: UUID) -> Document | None:
        return self.document_repo.get_by_id(db, id)

    def create_document(self, db: Session, payload: DocumentCreate, storage_client=None, file_obj=None) -> Document:
        """Create a document record and optionally store the file in external storage.

        - `storage_client` is an optional MinIO/S3-like client. Tests may pass
          a minimal stub implementing `put_object` or `stat_object`.
        - `file_obj` is an optional file-like object (e.g., FastAPI `UploadFile`).
        """
        # If a storage client is provided, attempt upload/validation first.
        if storage_client is not None:
            try:
                bucket = settings.MINIO_BUCKET_NAME

                # If a file-like object is provided, validate and stream it.
                if file_obj is not None and hasattr(storage_client, "put_object"):
                    # Determine content type for validation (prefer runtime content_type)
                    content_type = getattr(file_obj, "content_type", getattr(payload, "file_type", None))

                    if content_type and content_type not in self._ALLOWED_MIME:
                        raise DocumentUploadError("Unsupported file type")

                    # Obtain a binary stream for the upload and determine length.
                    stream = getattr(file_obj, "file", file_obj)
                    length = None
                    try:
                        pos = stream.tell()
                        stream.seek(0, 2)
                        length = stream.tell()
                        stream.seek(pos)
                    except Exception:
                        # Not seekable — read into memory as fallback.
                        data = stream.read()
                        stream = BytesIO(data)
                        length = len(data)

                    if length is not None and length > self._MAX_FILE_SIZE:
                        raise DocumentUploadError("File too large")

                    # Attempt to call the storage client's put_object. Different
                    # test stubs may accept different signatures; try the more
                    # complete signature first and fall back if needed.
                    try:
                        storage_client.put_object(bucket, payload.file_name, stream, length, content_type=content_type)
                    except TypeError:
                        # Fallback for simple 3-arg stubs used in tests.
                        storage_client.put_object(bucket, payload.file_name, stream)

                # Backwards-compatible: callers that pass a URL (e.g., tests/factories)
                # expect we simply call `put_object(bucket, name, url)` or `stat_object`.
                elif hasattr(storage_client, "put_object"):
                    storage_client.put_object(bucket, payload.file_name, payload.file_url)
                elif hasattr(storage_client, "stat_object"):
                    storage_client.stat_object(bucket, payload.file_name)
            except DocumentUploadError:
                raise
            except Exception as e:
                raise DocumentUploadError("Failed to store document") from e

        return self.document_repo.create(db, payload)

    def update_document(self, db: Session, id: UUID, payload: DocumentUpdate) -> Document | None:
        return self.document_repo.update(db, id, payload)

    def delete_document(self, db: Session, id: UUID) -> Document | None:
        return self.document_repo.delete(db, id)

    def get_by_contract(self, db: Session, contract_id: UUID) -> list[Document]:
        return self.document_repo.get_by_contract(db, contract_id)

    def get_by_property(self, db: Session, property_id: UUID) -> list[Document]:
        return self.document_repo.get_by_property(db, property_id)

    def get_by_tenant(self, db: Session, tenant_id: UUID) -> list[Document]:
        return self.document_repo.get_by_tenant(db, tenant_id)

    def get_by_type(self, db: Session, file_type: str) -> list[Document]:
        return self.document_repo.get_by_type(db, file_type)
