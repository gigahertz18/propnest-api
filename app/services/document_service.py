import logging

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4

from app.repositories.document import DocumentRepository
from app.repositories.contract import ContractRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate
from app.models.document import Document
from app.models.user import User, UserRole
from app.services.base import ResourceAuthorizationMixin
from app.services.exceptions import (
    DocumentUploadError,
    DocumentForbiddenError,
    RelatedResourceNotFoundError,
    DocumentDeletionError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentContext:
    """
    Fully prepared context for a document operation.

    After this object is returned:
    - all related resources have been validated to exist
    - authorization has been checked
    - property/contract/tenant resolution has been performed
    """

    document: Document | None
    property_id: UUID | None
    contract_id: UUID | None
    tenant_id: UUID | None


class DocumentService(ResourceAuthorizationMixin):
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
    forbidden_error = DocumentForbiddenError

    def __init__(
        self,
        document_repo: DocumentRepository,
        property_repo: PropertyRepository | None = None,
        contract_repo: ContractRepository | None = None,
        tenant_repo: TenantRepository | None = None,
    ) -> None:
        self.document_repo = document_repo
        self.property_repo = property_repo
        self.contract_repo = contract_repo
        self.tenant_repo = tenant_repo

    async def list_documents(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Document]:
        """Admins see every document. Managers only see documents tied to
        one of their own properties.

        `current_user` is required, not optional — see
        TenantService.list_tenants' docstring for why an optional,
        silently-skippable auth parameter is a footgun this codebase has
        already been bitten by once."""
        if current_user.role == UserRole.MANAGER:
            return await self.document_repo.get_all_for_manager(db, current_user.id, skip=skip, limit=limit)
        return await self.document_repo.get_all(db, skip=skip, limit=limit)

    async def get_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        current_user: User,
    ) -> Document:
        doc = await self.document_repo.get_by_id(db, doc_id)
        if not doc:
            raise RelatedResourceNotFoundError(f"Document {doc_id} not found.")
        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=doc.property_id,
            contract_id=doc.contract_id,
        )
        return doc

    async def create_document(
        self,
        db: AsyncSession,
        payload: DocumentCreate,
        storage_client=None,
        file_obj=None,
        current_user: User | None = None,
    ) -> Document:
        """Create a document record and optionally store the file in external storage.

        - `storage_client` is an optional MinIO/S3-like client. Tests may pass
          a minimal stub implementing `put_object` or `stat_object`.
        - `file_obj` is an optional file-like object (e.g., FastAPI `UploadFile`).
        """

        ctx = await self._prepare_document_context(
            db,
            doc=None,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
            tenant_id=payload.tenant_id,
            current_user=current_user,
        )

        doc_id = uuid4()
        storage_key = self._build_storage_key(doc_id, payload.file_name)
        file_url = (
            self.build_object_url(storage_key)
            if storage_client is not None and file_obj is not None
            else payload.file_url
        )

        resolved_payload = DocumentCreate(
            file_name=payload.file_name,
            file_type=payload.file_type,
            file_url=file_url,
            property_id=ctx.property_id,
            contract_id=ctx.contract_id,
            tenant_id=ctx.tenant_id,
        )

        create_payload = resolved_payload.model_dump()
        create_payload["id"] = doc_id
        # Step 1: upload to storage first - before any DB write.
        # If this fails, nothing is written to the DB
        if storage_client is not None and file_obj is not None:
            try:
                self._upload_to_storage(storage_client, storage_key, resolved_payload, file_obj)
            except Exception:
                raise  # let route handle this - no DB record created

        # Step 2: write DB record only after upload succeeds
        # If this failes, attempt to clean up the orphaned storage object
        try:
            document = await self.document_repo.create(db, create_payload)
            await db.commit()
            return document
        except Exception:
            if storage_client is not None and file_obj is not None:
                try:
                    self._delete_from_storage(storage_client, storage_key)
                except DocumentDeletionError:
                    logger.exception(
                        f"Orphaned storage object {storage_key} could not be cleaned up " f"after DB write failure."
                    )
            raise

    async def update_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        payload: DocumentRelinkUpdate,
        current_user: User | None = None,
    ) -> Document | None:

        doc = await self.get_document(db, doc_id, current_user=current_user)

        ctx = await self._prepare_document_context(
            db,
            doc=doc,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
            tenant_id=payload.tenant_id,
            current_user=current_user,
        )

        resolved_payload = DocumentRelinkUpdate(
            property_id=ctx.property_id,
            contract_id=ctx.contract_id,
            tenant_id=ctx.tenant_id,
        )

        doc = await self.document_repo.update(db, doc_id, resolved_payload)
        await db.commit()
        return doc

    async def replace_document_file(
        self,
        db: AsyncSession,
        doc_id: UUID,
        payload: DocumentFileUpdate,
        *,
        storage_client,
        file_obj,
        current_user: User | None = None,
    ) -> Document | None:
        """
        Replace the file behind an existing document, optionally updating its
        property, contract, or tenant association.

        The operation uploads the new file, updates the document record, and
        removes the old file after a successful commit. If the database update
        fails after the upload, the newly uploaded file is deleted to prevent
        orphaned storage objects.

        Raises:
            RelatedResourceNotFoundError: The document or a related resource was not found.
            DocumentForbiddenError: The current user is not authorized to modify the document.
            DocumentUploadError: Uploading the new file failed.
            DocumentDeletionError: Deleting the old file from storage failed.
        """
        doc = await self.get_document(db, doc_id, current_user=current_user)

        ctx = await self._prepare_document_context(
            db,
            doc=doc,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
            tenant_id=payload.tenant_id,
            current_user=current_user,
        )
        storage_key = self._build_storage_key(doc_id, payload.file_name)

        resolved_payload = DocumentFileUpdate(
            file_name=payload.file_name,
            file_type=payload.file_type,
            file_url=self.build_object_url(storage_key),
            property_id=ctx.property_id,
            contract_id=ctx.contract_id,
            tenant_id=ctx.tenant_id,
        )

        old_storage_key = self._build_storage_key(doc_id, doc.file_name)

        # Upload first — no DB write yet. _upload_to_storage only reads
        # file_name/file_type off its payload, so a SimpleNamespace avoids
        # needing a full DocumentCreate here.
        try:
            self._upload_to_storage(storage_client, storage_key, resolved_payload, file_obj)
        except:
            logger.exception("Storage upload failed for %s", storage_key)
            raise

        try:
            updated = await self.document_repo.update(db, doc_id, resolved_payload)
            await db.commit()
        except Exception:
            try:
                self._delete_from_storage(storage_client, storage_key)
            except DocumentDeletionError:
                logger.exception(
                    f"Orphaned storage object {storage_key} could not be cleaned up " f"after DB write failure."
                )
            raise

        if old_storage_key != storage_key:
            try:
                self._delete_from_storage(storage_client, old_storage_key)
            except DocumentDeletionError:
                logger.exception(
                    f"Orphaned old storage object {old_storage_key} could not be cleaned up "
                    f"after successful document update; need manual/async cleanup."
                )

        return updated

    async def delete_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        storage_client=None,
        current_user: User | None = None,
    ) -> Document | None:

        doc = await self.get_document(db, doc_id, current_user=current_user)

        await self._prepare_document_context(
            db,
            doc=doc,
            property_id=doc.property_id,
            contract_id=doc.contract_id,
            tenant_id=doc.tenant_id,
            current_user=current_user,
        )

        savepoint = await db.begin_nested()
        storage_key = self._build_storage_key(doc_id, doc.file_name)
        try:
            deleted = await self.document_repo.delete(db, doc_id)

            if deleted and storage_client is not None:
                self._delete_from_storage(storage_client, storage_key)

            await savepoint.commit()
            await db.commit()
            return deleted
        except DocumentDeletionError as exc:
            await savepoint.rollback()
            raise DocumentDeletionError(f"Document delete rolled back: {exc}") from exc
        except Exception:
            await savepoint.rollback()
            raise

    # ─── Reporting support ──────────────────────────────────────────────
    # Not yet called by any route — held here for an upcoming reporting
    # feature that will need documents filtered by contract/property/
    # tenant/type. If that feature is dropped, these should go with it.
    async def get_by_contract(self, db: AsyncSession, contract_id: UUID) -> Sequence[Document]:
        return await self.document_repo.get_by_contract(db, contract_id)

    async def get_by_property(self, db: AsyncSession, property_id: UUID) -> Sequence[Document]:
        return await self.document_repo.get_by_property(db, property_id)

    async def get_by_tenant(self, db: AsyncSession, tenant_id: UUID) -> Sequence[Document]:
        return await self.document_repo.get_by_tenant(db, tenant_id)

    async def get_by_type(self, db: AsyncSession, file_type: str) -> Sequence[Document]:
        return await self.document_repo.get_by_type(db, file_type)

    def build_object_url(self, storage_key: str) -> str:
        """
        Build the public-facing URL for a stored object.
        Format : {endpoint}/{bucket}/{file_name}
        """
        endpoint = settings.MINIO_ENDPOINT.rstrip("/")
        bucket = settings.MINIO_BUCKET_NAME
        return f"{endpoint}/{bucket}/{storage_key}"

    def _upload_to_storage(
        self,
        storage_client,
        storage_key: str,
        payload: DocumentCreate | DocumentFileUpdate,
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
                storage_key,
                stream,
                length,
                content_type=content_type,
            )
        except Exception as e:
            raise DocumentUploadError(f"Storage upload failed: {e}") from e

    def _delete_from_storage(self, storage_client, storage_key: str) -> None:
        try:
            storage_client.remove_object(settings.MINIO_BUCKET_NAME, storage_key)
        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned. storage object after DB write failure: {storage_key}")
            raise DocumentDeletionError(f"File deletion failed: {e}")

    async def _prepare_document_context(
        self,
        db: AsyncSession,
        *,
        doc: Document | None = None,
        property_id: UUID | None = None,
        contract_id: UUID | None = None,
        tenant_id: UUID | None = None,
        current_user: User | None = None,
    ) -> DocumentContext:
        """
        Prepare a DocumentContext for a document operation.

        - Resolves the property/contract/tenant context.
        - Validates that any provided property_id, contract_id, or tenant_id exist.
        - Authorizes the current_user against the resolved property/contract.

        Raises:
            RelatedResourceNotFoundError: if any provided property_id,
                contract_id, or tenant_id doesn't exist.
            DocumentForbiddenError: if current_user isn't authorized to
                manage the resolved property/contract.
        """
        effective_property_id = property_id if property_id is not None else doc.property_id if doc else None
        effective_contract_id = contract_id if contract_id is not None else doc.contract_id if doc else None
        effective_tenant_id = tenant_id if tenant_id is not None else doc.tenant_id if doc else None

        await self._validate_related_resources(
            db,
            property_id=effective_property_id,
            contract_id=effective_contract_id,
            tenant_id=effective_tenant_id,
        )

        if current_user:
            await self._authorize_user_to_property(
                db,
                current_user,
                property_id=effective_property_id,
                contract_id=effective_contract_id,
            )

        return DocumentContext(
            document=doc,
            property_id=effective_property_id,
            contract_id=effective_contract_id,
            tenant_id=effective_tenant_id,
        )

    def _build_storage_key(self, document_id: UUID, file_name: str) -> str:
        filename = Path(file_name).name

        return f"documents/{document_id}_{filename}"
