from __future__ import annotations

import logging
import tempfile

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4


from app.core.config import settings
from app.core.models.audit_log import AuditAction
from app.models.contract import Contract
from app.models.document import Document
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.collection import CollectionRepository
from app.repositories.contract import ContractRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.core.schemas.base import PaginatedResponse
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate
from app.core.services.audit import write_audit_log
from app.core.services.base import ResourceAuthorizationMixin
from app.core.services.exceptions import (
    DocumentUploadError,
    DocumentForbiddenError,
    DocumentStorageInconsistentError,
    DocumentValidationError,
    RelatedResourceNotFoundError,
    DocumentDeletionError,
    ServiceException,
)

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
    collection_id: UUID | None


class DocumentService(ResourceAuthorizationMixin):
    """Business logic for `Document` entities.

    Optionally accepts a storage client (e.g., MinIO) for uploading files.
    Given a file-like object (`file_obj`), the service validates MIME/size
    and streams it to storage. The MIME type is sniffed from the file's own magic bytes,
    never trusted from `file_obj.content_type` or `payload.file_type`. Errors are translated
    to domain exceptions for the route layer.
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

    _SIGNATURE_PEEK_SIZE = 4096
    # Bound each read from the incoming stream so a single call never
    # pulls more than one chunk into memory at a time.
    _UPLOAD_CHUNK_SIZE = 64 * 1024
    # SpooledTemporaryFile stays in-memory up to this size, then
    # transparently spills to disk — caps per-request resident memory
    # regardless of _MAX_FILE_SIZE.
    _SPOOL_MAX_SIZE = 1 * 1024 * 1024
    _PDF_MAGIC = b"%PDF-"
    _PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    _JPEG_MAGIC = b"\xff\xd8\xff"
    _MSWORD_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    _ZIP_MAGIC = b"PK\x03\x04"

    forbidden_error = DocumentForbiddenError

    def __init__(
        self,
        document_repo: DocumentRepository,
        property_repo: PropertyRepository | None = None,
        contract_repo: ContractRepository | None = None,
        tenant_repo: TenantRepository | None = None,
        collection_repo: CollectionRepository | None = None,
    ) -> None:
        self.document_repo = document_repo
        self.property_repo = property_repo
        self.contract_repo = contract_repo
        self.tenant_repo = tenant_repo
        self.collection_repo = collection_repo

    async def list_documents(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[Document]:
        """Admins see every document; managers only see documents tied
        to one of their own properties."""
        return await self._list_scoped_by_manager(db, current_user, self.document_repo, skip, limit)

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

    async def get_document_content(
        self,
        db: AsyncSession,
        doc_id: UUID,
        current_user: User,
        storage_client,
    ) -> tuple[Document, bytes]:
        """Fetch a document's metadata (authorized via `get_document`) and
        its raw bytes from storage. Raises ServiceException if the DB
        record exists but the object can't be read back from storage."""
        document = await self.get_document(db, doc_id, current_user)
        storage_key = self._build_storage_key(document.id, document.file_name)
        try:
            response = storage_client.get_object(settings.MINIO_BUCKET_NAME, storage_key)
            try:
                data = response.read()
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
                release_conn = getattr(response, "release_conn", None)
                if release_conn:
                    release_conn()
        except Exception as e:
            raise ServiceException(f"Failed to read document {doc_id} from storage: {e}") from e
        return document, data

    async def create_document(
        self,
        db: AsyncSession,
        payload: DocumentCreate,
        current_user: User,
        storage_client=None,
        file_obj=None,
    ) -> Document:
        """Create a document record and optionally store the file in external storage.

        - `storage_client` is an optional MinIO/S3-like client. Tests may pass
          a minimal stub implementing `put_object` or `stat_object`.
        - `file_obj` is an optional file-like object (e.g., FastAPI `UploadFile`).
        """

        ctx = await self._prepare_document_context(
            db,
            current_user,
            doc=None,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
            tenant_id=payload.tenant_id,
            collection_id=payload.collection_id,
        )

        doc_id = uuid4()
        storage_key = self._build_storage_key(doc_id, payload.file_name)

        file_url = self.build_object_url(storage_key)

        create_payload = {
            "id": doc_id,
            "file_name": payload.file_name,
            "file_type": payload.file_type,
            "file_url": file_url,
            "property_id": ctx.property_id,
            "contract_id": ctx.contract_id,
            "tenant_id": ctx.tenant_id,
            "collection_id": ctx.collection_id,
        }
        # Step 1: upload to storage first - before any DB write.
        # If this fails, nothing is written to the DB
        if storage_client is not None and file_obj is not None:
            try:
                self._upload_to_storage(storage_client, storage_key, payload, file_obj)
            except Exception:
                raise  # let route handle this - no DB record created

        # Step 2: write DB record only after upload succeeds
        # If this failes, attempt to clean up the orphaned storage object
        try:
            document = await self.document_repo.create(db, create_payload)
            write_audit_log(db, current_user, AuditAction.CREATE, "Document", doc_id)
            await db.commit()
            return document
        except Exception:
            if storage_client is not None and file_obj is not None:
                try:
                    self._delete_from_storage(storage_client, storage_key)
                except DocumentDeletionError:
                    logger.exception(
                        f"Orphaned storage object {storage_key} could not be cleaned up after DB write failure."
                    )
            raise

    async def update_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        payload: DocumentRelinkUpdate,
        current_user: User,
    ) -> Document | None:

        doc = await self.get_document(db, doc_id, current_user=current_user)

        ctx = await self._prepare_document_context(
            db,
            current_user,
            doc=doc,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
            tenant_id=payload.tenant_id,
            collection_id=payload.collection_id,
        )

        resolved_payload = DocumentRelinkUpdate(
            property_id=ctx.property_id,
            contract_id=ctx.contract_id,
            tenant_id=ctx.tenant_id,
            collection_id=ctx.collection_id,
        )

        doc = await self.document_repo.update(db, doc_id, resolved_payload)
        write_audit_log(db, current_user, AuditAction.UPDATE, "Document", doc_id)
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
        current_user: User,
    ) -> Document | None:
        """
        Replace the file behind an existing document, optionally
        updating its property/contract/tenant association.

        Upload flow: stage the new file under a one-off key, commit the
        DB update, then promote to the canonical key and remove the old file.
        The current file is never touched until the DB update commits,
        so a failure anywhere leaves the original file intact - even when the new and old filename
        are the same.

        Raises:
            RelatedResourceNotFoundError: document or related resource not found.
            DocumentForbiddenError: current_user not authorized.
            DocumentUploadError: uploading the new file failed (nothing persisted).
            DocumentStorageInconsistentError: DB committed but promotion failed - needs manual remediation
            DocumentDeletionError: deleting the old file from storage failed.
        """
        doc = await self.get_document(db, doc_id, current_user=current_user)

        ctx = await self._prepare_document_context(
            db,
            current_user,
            doc=doc,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
            tenant_id=payload.tenant_id,
            collection_id=payload.collection_id,
        )
        storage_key = self._build_storage_key(doc_id, payload.file_name)
        old_storage_key = self._build_storage_key(doc_id, doc.file_name)

        resolved_payload = {
            "file_name": payload.file_name,
            "file_type": payload.file_type,
            "file_url": self.build_object_url(storage_key),
            "property_id": ctx.property_id,
            "contract_id": ctx.contract_id,
            "tenant_id": ctx.tenant_id,
            "collection_id": ctx.collection_id,
        }

        # Read once so the same spooled stream can be written to more than
        # one storage key without re-reading file_obj (single-pass read of
        # the source; `_put_object` reseeks it for each destination write).
        spooled, content_type, size = self._read_and_validate_upload(resolved_payload, file_obj)

        try:
            # Stage to one-off key first - never directly to storage_key,
            # which may equal old_storage_key (unchanged filename) and is
            # where the current, still-DB-reference file lives until the update below commits
            staging_key = self._build_staging_key(doc_id)
            self._put_object(storage_client, staging_key, spooled, size, content_type)

            updated = await self._commit_file_replacement(
                db,
                doc_id,
                resolved_payload,
                storage_client,
                staging_key,
                current_user,
            )
            self._promote_staged_upload(
                storage_client,
                doc_id,
                staging_key,
                storage_key,
                spooled,
                size,
                content_type,
            )
            self._finalize_replacement_cleanup(storage_client, staging_key, old_storage_key, storage_key)
        finally:
            spooled.close()

        return updated

    async def _commit_file_replacement(
        self,
        db: AsyncSession,
        doc_id: UUID,
        resolved_payload: DocumentFileUpdate,
        storage_client,
        staging_key: str,
        current_user: User,
    ) -> Document | None:
        """Commit the DB update; on failure, remove the now-orphaned
        staging object and re-raise the original error."""
        try:
            updated = await self.document_repo.update(db, doc_id, resolved_payload)
            write_audit_log(db, current_user, AuditAction.UPDATE, "Document", doc_id)
            await db.commit()
            return updated
        except Exception:
            try:
                self._delete_from_storage(storage_client, staging_key)
            except DocumentDeletionError:
                logger.exception(
                    f"Orphaned staging object {staging_key} could not be cleaned up after DB write failure."
                )
            raise

    def _promote_staged_upload(
        self,
        storage_client,
        doc_id: UUID,
        staging_key: str,
        storage_key: str,
        stream,
        size: int,
        content_type: str,
    ) -> None:
        """DB commit succeeded - promote the staged bytes to the
        canonical key. Failure here means the row and storage are out of sync
        and need manual repair."""

        try:
            self._put_object(storage_client, storage_key, stream, size, content_type)
        except DocumentUploadError as exc:
            logger.critical(
                f"Promoting staged upload {staging_key} to {storage_key} for Document {doc_id} failed; "
                f"DB and Storage are now inconsistent. Please investigate."
            )
            raise DocumentStorageInconsistentError(f"File replacement failed: {exc}") from exc

    def _finalize_replacement_cleanup(
        self,
        storage_client,
        staging_key: str,
        old_storage_key: str,
        storage_key: str,
    ) -> None:
        """Best-effort cleanup after a successful promotion: remove the staging object,
        and the old file if its key differs from the new one. Failures are logged,
        not raised - the document is already correctly updated."""

        try:
            self._delete_from_storage(storage_client, staging_key)
        except DocumentDeletionError:
            logger.exception(f"Staging object {staging_key} could not be cleaned up after successful promotion.")

        if old_storage_key != storage_key:
            try:
                self._delete_from_storage(storage_client, old_storage_key)
            except DocumentDeletionError:
                logger.exception(
                    f"Orphaned old storage object {old_storage_key} could not be cleaned up "
                    f"after successful document update; needs manual cleanup."
                )

    async def delete_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        current_user: User,
        storage_client=None,
    ) -> Document | None:

        doc = await self.get_document(db, doc_id, current_user=current_user)

        storage_key = self._build_storage_key(doc_id, doc.file_name)

        try:
            deleted = await self.document_repo.delete(db, doc_id)
            write_audit_log(db, current_user, AuditAction.DELETE, "Document", doc_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        # The DB row is gone and durably committed. The storage object is
        # irreversible once removed, so it's deleted only after that point
        # is guaranteed - never inside a transaction that might not commit.
        # A failure here can't be rolled back either way, so it's logged as
        # an orphan for manual/scheduled cleanup rather than raised: the
        # delete already succeeded from the caller's point of view.
        if deleted and storage_client is not None:
            try:
                self._delete_from_storage(storage_client, storage_key)
            except DocumentDeletionError:
                logger.error(
                    f"Document {doc_id} deleted from DB but storage object "
                    f"{storage_key} could not be removed; orphaned in MinIO "
                    f"and needs manual cleanup."
                )

        return deleted

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
        """Validate and stream file to storage. Raises
        DocumentUploadError on failure. The real type is sniffed from
        magic bytes, never trusted from `file_obj.content_type` or
        `payload.file_type` alone."""

        spooled, content_type, size = self._read_and_validate_upload(payload, file_obj)
        try:
            self._put_object(storage_client, storage_key, spooled, size, content_type)
        finally:
            spooled.close()

    def _read_and_validate_upload(
        self,
        payload: DocumentCreate | DocumentFileUpdate,
        file_obj,
    ) -> tuple[tempfile.SpooledTemporaryFile, str, int]:
        """Read `file_obj` and validate it, without touching storage.
        Returns `(spooled_file, sniffed_content_type, size)` so the same
        validated stream can be written to more than one storage key
        (see `replace_document_file`) — callers are responsible for
        closing `spooled_file` once done. Raises DocumentUploadError on
        any validation failure."""

        stream = getattr(file_obj, "file", file_obj)
        declared_type = getattr(file_obj, "content_type", None) or payload.file_type

        # "image/jpg" is a non-standard but common alias for "image/jpeg"
        # treat it as a match rather than a mismatch when sniffed as JPEG.
        if declared_type == "image/jpg":
            declared_type = "image/jpeg"

        # Peek a small prefix first - enough to sniff the signature,
        # so we can reject mislabled/oversized upload without buffering the whole body in memory.
        prefix = stream.read(self._SIGNATURE_PEEK_SIZE)
        sniffed_type = self._sniff_content_type(prefix)

        if sniffed_type is None or sniffed_type not in self._ALLOWED_MIME:
            logger.warning(
                "Rejected upload %s: signature did not match an allowed type "
                "(client declared content_type=%r, file_type=%r)",
                payload.file_name,
                getattr(file_obj, "content_type", None),
                payload.file_type,
            )
            raise DocumentUploadError("Unsupported file type")

        if sniffed_type != declared_type:
            raise DocumentUploadError("File type mismatch")

        # Stream the remainder into a spooled file in bounded chunks,
        # capped one byte past the size limit so an oversized file is
        # detected without ever holding the full body as one contiguous
        # in-memory buffer. Below _SPOOL_MAX_SIZE this behaves like a
        # BytesIO; above it, it spills to disk instead of the heap.
        spooled = tempfile.SpooledTemporaryFile(max_size=self._SPOOL_MAX_SIZE)
        try:
            spooled.write(prefix)
            total = len(prefix)
            remaining_cap = self._MAX_FILE_SIZE + 1 - total
            while remaining_cap > 0:
                chunk = stream.read(min(self._UPLOAD_CHUNK_SIZE, remaining_cap))
                if not chunk:
                    break
                spooled.write(chunk)
                total += len(chunk)
                remaining_cap -= len(chunk)

            if total > self._MAX_FILE_SIZE:
                raise DocumentUploadError("File too large")
        except Exception:
            spooled.close()
            raise

        spooled.seek(0)
        return spooled, sniffed_type, total

    def _put_object(
        self,
        storage_client,
        storage_key: str,
        stream,
        size: int,
        content_type: str,
    ) -> None:
        """Write an already-validated, seekable stream to `storage_key`.
        Seeks to the start first so the same stream can be reused across
        multiple destinations (see `replace_document_file`). Raises
        DocumentUploadError on failure."""
        bucket = settings.MINIO_BUCKET_NAME
        stream.seek(0)
        try:
            storage_client.put_object(
                bucket,
                storage_key,
                stream,
                size,
                content_type=content_type,
            )
        except Exception as e:
            raise DocumentUploadError(f"Storage upload failed: {e}") from e

    def _sniff_content_type(self, data: bytes) -> str | None:
        """Determine a file's actual MIME type from its magic
        bytes/signature (`data` is a prefix — see
        `_SIGNATURE_PEEK_SIZE`). Returns None if unrecognized; callers
        still check the result against `_ALLOWED_MIME`."""

        if data.startswith(self._PDF_MAGIC):
            return "application/pdf"
        if data.startswith(self._PNG_MAGIC):
            return "image/png"
        if data.startswith(self._JPEG_MAGIC):
            return "image/jpeg"
        if data.startswith(self._MSWORD_MAGIC):
            return "application/msword"
        if data.startswith(self._ZIP_MAGIC):
            # .docx (00XML) is a ZIP container and shares the ZIP magic;
            # legacy .doc uses the OLE compound-file signature above instead,
            # so the two never collides
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return None

    def _delete_from_storage(self, storage_client, storage_key: str) -> None:
        try:
            storage_client.remove_object(settings.MINIO_BUCKET_NAME, storage_key)
        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned storage object after DB write failure: {storage_key}")
            raise DocumentDeletionError(f"File deletion failed: {e}")

    async def _prepare_document_context(
        self,
        db: AsyncSession,
        current_user: User,
        *,
        doc: Document | None = None,
        property_id: UUID | None = None,
        contract_id: UUID | None = None,
        tenant_id: UUID | None = None,
        collection_id: UUID | None = None,
    ) -> DocumentContext:
        """Resolve, normalize, and authorize the property/contract/tenant/collection context.

        Contract-backed documents are normalized through a single helper so the  contract
        remains the source of truth and the contract/property/tenant checks stay in one place.

        Raises:
            RelatedResourceNotFoundError: an id was provided but doesn't exist.
            DocumentForbiddenError: current_user isn't authorized.
            DocumentValidationError: provided relationship ids conflict with each other.
        """

        resolved_prop_id, resolved_contract_id, resolved_tenant_id, resolved_collection_id, contract = (
            await self._resolve_document_relationship(
                db,
                doc=doc,
                property_id=property_id,
                contract_id=contract_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
            )
        )

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=resolved_prop_id,
            contract_id=resolved_contract_id,
            contract=contract,
        )

        return DocumentContext(
            document=doc,
            property_id=resolved_prop_id,
            contract_id=resolved_contract_id,
            tenant_id=resolved_tenant_id,
            collection_id=resolved_collection_id,
        )

    async def _resolve_document_relationship(
        self,
        db: AsyncSession,
        *,
        doc: Document | None,
        property_id: UUID | None,
        contract_id: UUID | None,
        tenant_id: UUID | None,
        collection_id: UUID | None,
    ) -> tuple[UUID | None, UUID | None, UUID | None, UUID | None, Contract | None]:
        """Normalize the relationship ids for document write operations.

        If a contract is present, it is the source of truth and any supplied
        property_id / tenant_id must match it. `collection_id` is independent
        of the contract — only existence is validated, not ownership.
        """
        resolved_ids = self._resolve_ids(
            doc,
            property_id=property_id,
            contract_id=contract_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
        )

        effective_contract_id = resolved_ids.get("contract_id")
        resolved_property_id = resolved_ids.get("property_id")
        resolved_tenant_id = resolved_ids.get("tenant_id")
        resolved_collection_id = resolved_ids.get("collection_id")

        if not effective_contract_id:
            await self._validate_related_resources(
                db,
                property_id=resolved_property_id,
                tenant_id=resolved_tenant_id,
                collection_id=resolved_collection_id,
            )
            return resolved_property_id, None, resolved_tenant_id, resolved_collection_id, None

        contract = await self._get_contract(db, effective_contract_id)
        if contract is None:
            raise RelatedResourceNotFoundError(f"Contract {effective_contract_id} not found.")

        await self._validate_related_resources(
            db,
            property_id=resolved_property_id,
            tenant_id=resolved_tenant_id,
            collection_id=resolved_collection_id,
        )

        if resolved_property_id and resolved_property_id != contract.property_id:
            raise DocumentValidationError(
                f"Property {resolved_property_id} does not match contract {effective_contract_id}"
            )
        if resolved_tenant_id and resolved_tenant_id != contract.tenant_id:
            raise DocumentValidationError(
                f"Tenant {resolved_tenant_id} does not match contract {effective_contract_id}"
            )

        return contract.property_id, contract.id, contract.tenant_id, resolved_collection_id, contract

    def _build_storage_key(self, document_id: UUID, file_name: str) -> str:
        filename = Path(file_name).name

        return f"documents/{document_id}_{filename}"

    def _build_staging_key(self, document_id: UUID) -> str:
        """Build a one-off key for a staged upload — never a document's
        canonical key. Namespaced under `documents/_staging/` (a prefix
        `_build_storage_key` never produces) and suffixed with a random
        token so concurrent replacements can't collide."""
        return f"documents/_staging/{document_id}_{uuid4().hex}"
