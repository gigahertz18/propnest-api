import logging

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO

from app.repositories.document import DocumentRepository
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.models.document import Document
from app.services.exceptions import DocumentUploadError
from app.core.config import settings

logger = logging.getLogger(__name__)


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

    async def list_documents(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Document]:
        return await self.document_repo.get_all(db, skip=skip, limit=limit)

    async def get_document(self, db: AsyncSession, id: UUID) -> Document | None:
        return await self.document_repo.get_by_id(db, id)

    async def create_document(
        self, db: AsyncSession, payload: DocumentCreate, storage_client=None, file_obj=None
    ) -> Document:
        """Create a document record and optionally store the file in external storage.

        - `storage_client` is an optional MinIO/S3-like client. Tests may pass
          a minimal stub implementing `put_object` or `stat_object`.
        - `file_obj` is an optional file-like object (e.g., FastAPI `UploadFile`).
        """
        # Step 1: upload to storage first - before any DB write.
        # If this fails, nothing is written to the DB
        if storage_client is not None and file_obj is not None:
            try:
                self._upload_to_storage(storage_client, payload, file_obj)
            except Exception:
                raise  # let route handle this - no DB record created

        # Step 2: write DB record only after upload succeeds
        # If this failes, attempt to clean up the orphaned storage object
        try:
            document = await self.document_repo.create(db, payload)
            await db.commit()
            return document
        except Exception:
            if storage_client is not None and file_obj is not None:
                self._delete_from_storage(storage_client, payload.file_name)
            raise

    async def update_document(self, db: AsyncSession, id: UUID, payload: DocumentUpdate) -> Document | None:
        doc = await self.document_repo.update(db, id, payload)
        await db.commit()
        return doc

    async def delete_document(self, db: AsyncSession, id: UUID) -> Document | None:
        doc = await self.document_repo.delete(db, id)
        await db.commit()
        return doc

    async def get_by_contract(self, db: AsyncSession, contract_id: UUID) -> list[Document]:
        return await self.document_repo.get_by_contract(db, contract_id)

    async def get_by_property(self, db: AsyncSession, property_id: UUID) -> list[Document]:
        return await self.document_repo.get_by_property(db, property_id)

    async def get_by_tenant(self, db: AsyncSession, tenant_id: UUID) -> list[Document]:
        return await self.document_repo.get_by_tenant(db, tenant_id)

    async def get_by_type(self, db: AsyncSession, file_type: str) -> list[Document]:
        return await self.document_repo.get_by_type(db, file_type)

    def _build_object_url(self, file_name: str) -> str:
        """
        Build the public-facing URL for a stored object.
        Format : {endpoint}/{bucket}/{file_name}
        """
        endpoint = settings.MINIO_ENDPOINT.rstrip("/")
        bucket = settings.MINIO_BUCKET_NAME
        return f"{endpoint}/{bucket}/{file_name}"

    def _upload_to_storage(
        self,
        storage_client,
        payload: DocumentCreate,
        file_obj,
    ) -> None:
        """
        Validate and stream file to storage. Raises DocumentUploadError on failure.
        """
        bucket = settings.MINIO_BUCKET_NAME

        content_type = getattr(file_obj, "content_type", None) or payload.file_type
        if content_type and content_type not in self._ALLOWED_MIME:
            raise DocumentUploadError("Unsupported file type")

        stream = getattr(file_obj, "file", file_obj)
        length = None

        try:
            pos = stream.tell()
            stream.seek(0, 2)
            length = stream.tell()
            stream.seek(pos)
        except Exception:
            data = stream.read()
            stream = BytesIO(data)
            length = len(data)

        if length is not None and length > self._MAX_FILE_SIZE:
            raise DocumentUploadError("File too large")

        try:
            storage_client.put_object(
                bucket,
                payload.file_name,
                stream,
                length,
                content_type=content_type,
            )
        except Exception as e:
            raise DocumentUploadError(f"Storage upload failed: {e}") from e

    def _delete_from_storage(self, storage_client, file_name: str) -> None:
        try:
            storage_client.remove_object(settings.MINIO_BUCKET_NAME, file_name)
        except Exception:
            logger.warning(f"Failed to cleanup orphaned. storage object after DB write failure: {file_name}")
