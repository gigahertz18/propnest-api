from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.document import DocumentRepository
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.models.document import Document
from app.services.exceptions import DocumentUploadError
from app.core.config import settings


class DocumentService:
    """Business logic for `Document` entities.

    Optionally accepts a storage client (e.g., MinIO) for uploading files.
    The storage client is not required for simple metadata-only flows but is
    supported and errors are translated to domain exceptions so routes can
    respond appropriately.
    """

    def __init__(self, document_repo: DocumentRepository) -> None:
        self.document_repo = document_repo

    def list_documents(self, db: Session, skip: int = 0, limit: int = 100) -> list[Document]:
        return self.document_repo.get_all(db, skip=skip, limit=limit)

    def get_document(self, db: Session, id: UUID) -> Document | None:
        return self.document_repo.get_by_id(db, id)

    def create_document(self, db: Session, payload: DocumentCreate, storage_client=None) -> Document:
        # If a storage client is provided, attempt upload/validation first.
        if storage_client is not None:
            try:
                # Client contract varies; callers/tests should provide a
                # minimal stub implementing the required methods (e.g., put_object).
                # Use the configured bucket name (not payload.file_url) as the
                # target bucket. Payloads are expected to provide a usable
                # object name in `file_name` and either raw data or a URL in
                # `file_url` depending on the caller's contract.
                bucket = settings.MINIO_BUCKET_NAME
                if hasattr(storage_client, "put_object"):
                    # Minimal call: (bucket_name, object_name, data)
                    storage_client.put_object(bucket, payload.file_name, payload.file_url)
                elif hasattr(storage_client, "stat_object"):
                    storage_client.stat_object(bucket, payload.file_name)
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
