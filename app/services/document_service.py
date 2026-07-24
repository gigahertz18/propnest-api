from __future__ import annotations

import logging

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4


from app.core.config import settings
from app.models.document import Document
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.contract import ContractRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.schemas.base import PaginatedResponse
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate
from app.services.base import ResourceAuthorizationMixin
from app.services.exceptions import (
    DocumentUploadError,
    DocumentForbiddenError,
    DocumentStorageInconsistentError,
    RelatedResourceNotFoundError,
    DocumentDeletionError,
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


class DocumentService(ResourceAuthorizationMixin):
    """Business logic for `Document` entities.

    Optionally accepts a storage client (e.g., MinIO) for uploading files.
    When given a file-like object (`file_obj`), the service validates
    MIME/size and streams it to storage. The MIME type used for
    validation is sniffed from the file's own magic bytes/signature —
    `file_obj.content_type` and `payload.file_type` are request-supplied
    metadata and are never trusted for this, since both are
    attacker-controlled and neither reflects the actual bytes uploaded.
    Errors are translated to domain exceptions so routes can respond appropriately.
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
                        f"Orphaned storage object {storage_key} could not be cleaned up after DB write failure."
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
        Replace the file behind an existing document, optionally
        updating its property/contract/tenant association.

        Upload flow: stage the new file under a one-off key, commit the
        DB update, then promote the staged bytes to the canonical key
        and remove the old file. The document's *current* file is never
        touched until the DB update commits, so any failure along the
        way leaves the original file intact — even when the new and old
        filenames are the same and would otherwise share a key.

        Raises:
            RelatedResourceNotFoundError: document or related resource not found.
            DocumentForbiddenError: current_user not authorized.
            DocumentUploadError: uploading the new file failed (nothing persisted).
            DocumentStorageInconsistentError: DB committed but promoting the staged
                upload to its canonical key failed — needs manual remediation.
            DocumentDeletionError: deleting the old file from storage failed.
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
        old_storage_key = self._build_storage_key(doc_id, doc.file_name)

        resolved_payload = DocumentFileUpdate(
            file_name=payload.file_name,
            file_type=payload.file_type,
            file_url=self.build_object_url(storage_key),
            property_id=ctx.property_id,
            contract_id=ctx.contract_id,
            tenant_id=ctx.tenant_id,
        )

        # Read once so the same bytes can be written to more than one
        # storage key without re-reading file_obj (single-pass stream)
        data, content_type = self._read_and_validate_upload(resolved_payload, file_obj)

        # Stage to one-off key first - never directly to storage_key,
        # which may equal old_storage_key (unchanged filename) and is
        # where the current, still-DB-reference file lives until the update below commits
        staging_key = self._build_staging_key(doc_id)
        self._put_object(storage_client, staging_key, data, content_type)

        updated = await self._commit_file_replacement(
            db,
            doc_id,
            resolved_payload,
            storage_client,
            staging_key,
        )
        self._promote_staged_upload(
            storage_client,
            doc_id,
            staging_key,
            storage_key,
            data,
            content_type,
        )
        self._finalize_replacement_cleanup(storage_client, staging_key, old_storage_key, storage_key)

        return updated

    async def _commit_file_replacement(
        self,
        db: AsyncSession,
        doc_id: UUID,
        resolved_payload: DocumentFileUpdate,
        storage_client,
        staging_key: str,
    ) -> Document | None:
        """Commit the DB update; on failure, remove the now-orphaned
        staging object and re-raise the original error."""
        try:
            updated = await self.document_repo.update(db, doc_id, resolved_payload)
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
        data: bytes,
        content_type: str,
    ) -> None:
        """DB commit succeeded - promote the staged bytes to the
        canonical key. Failure here means the row and storage are out of sync
        and need manual repair."""

        try:
            self._put_object(storage_client, storage_key, data, content_type)
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
        not riased - the document is already correctly updated."""

        try:
            self._delete_from_storage(storage_client, staging_key)
        except DocumentDeletionError:
            logger.exception(f"Staging object {staging_key} could not be cleaned up after succesful promotion.")

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
        """Validate and stream file to storage. Raises
        DocumentUploadError on failure. The real type is sniffed from
        magic bytes, never trusted from `file_obj.content_type` or
        `payload.file_type` alone."""

        data, content_type = self._read_and_validate_upload(payload, file_obj)
        self._put_object(storage_client, storage_key, data, content_type)

    def _read_and_validate_upload(
        self,
        payload: DocumentCreate | DocumentFileUpdate,
        file_obj,
    ) -> tuple[bytes, str]:
        """Read `file_obj` fully into memory and validate it, without
        touching storage. Returns `(data, sniffed_content_type)` so the
        same validated bytes can be written to more than one storage key
        (see `replace_document_file`). Raises DocumentUploadError on
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

        # Now read the remainder, capped one byte past the size limit
        # so we can detect an oversized file without loading it all into memory.
        remaining_cap = self._MAX_FILE_SIZE + 1 - len(prefix)
        remainder = stream.read(remaining_cap) if remaining_cap > 0 else b""
        data = prefix + remainder
        if data is not None and len(data) > self._MAX_FILE_SIZE:
            raise DocumentUploadError("File too large")

        return data, sniffed_type

    def _put_object(
        self,
        storage_client,
        storage_key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        """Write already-validated bytes to `storage_key`. Raises
        DocumentUploadError on failure."""
        bucket = settings.MINIO_BUCKET_NAME
        try:
            storage_client.put_object(
                bucket,
                storage_key,
                BytesIO(data),
                len(data),
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
        *,
        doc: Document | None = None,
        property_id: UUID | None = None,
        contract_id: UUID | None = None,
        tenant_id: UUID | None = None,
        current_user: User | None = None,
    ) -> DocumentContext:
        """Resolve the property/contract/tenant context, validate any
        provided ids exist, and authorize current_user against the
        resolved property/contract.

        Raises:
            RelatedResourceNotFoundError: an id was provided but doesn't exist.
            DocumentForbiddenError: current_user isn't authorized.
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

    def _build_staging_key(self, document_id: UUID) -> str:
        """Build a one-off key for a staged upload — never a document's
        canonical key. Namespaced under `documents/_staging/` (a prefix
        `_build_storage_key` never produces) and suffixed with a random
        token so concurrent replacements can't collide."""
        return f"documents/_staging/{document_id}_{uuid4().hex}"
