import logging

from io import BytesIO
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID

from app.repositories.document import DocumentRepository
from app.repositories.contract import ContractRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate
from app.models.document import Document
from app.models.property import Property
from app.models.user import User, UserRole
from app.services.exceptions import (
    DocumentUploadError,
    DocumentForbiddenError,
    RelatedResourceNotFoundError,
    DocumentDeletionError,
)
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

    async def _get_property(self, db: AsyncSession, property_id: UUID) -> Property | None:
        """Single-entity lookup primitive. `_resolve_property` and
        `_validate_related_resources` both build on this rather than each
        calling `property_repo.get_by_id` independently — keeps "how to
        fetch a property" in exactly one place."""
        if self.property_repo is None:
            raise RuntimeError("DocumentService._get_property requires property_repo to be injected.")
        return await self.property_repo.get_by_id(db, property_id)

    async def _get_contract(self, db: AsyncSession, contract_id: UUID):
        if self.contract_repo is None:
            raise RuntimeError("DocumentService._get_contract requires contract_repo to be injected.")
        return await self.contract_repo.get_by_id(db, contract_id)

    async def _get_tenant(self, db: AsyncSession, tenant_id: UUID):
        if self.tenant_repo is None:
            raise RuntimeError("DocumentService._get_tenant requires tenant_repo to be injected.")
        return await self.tenant_repo.get_by_id(db, tenant_id)

    async def list_documents(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Document]:
        return await self.document_repo.get_all(db, skip=skip, limit=limit)

    async def get_document(self, db: AsyncSession, doc_id: UUID) -> Document | None:
        doc = await self.document_repo.get_by_id(db, doc_id)
        if not doc:
            raise RelatedResourceNotFoundError(f"Document {doc_id} not found.")
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
        if any([self.property_repo, self.contract_repo, self.tenant_repo]):
            await self._validate_related_resources(
                db, property_id=payload.property_id, contract_id=payload.contract_id, tenant_id=payload.tenant_id
            )

        if current_user:
            await self._authorize_user_to_property(
                db,
                current_user,
                property_id=payload.property_id,
                contract_id=payload.contract_id,
            )

        if payload.tenant_id:
            logger.info(f"Creating document linked to {payload.tenant_id}.")

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

    async def update_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        payload: DocumentRelinkUpdate,
        current_user: User | None = None,
    ) -> Document | None:

        if any([self.property_repo, self.contract_repo, self.tenant_repo]):
            await self._validate_related_resources(
                db,
                property_id=payload.property_id,
                contract_id=payload.contract_id,
                tenant_id=payload.tenant_id,
            )

        doc = await self.document_repo.get_by_id(db, doc_id)

        if not doc:
            raise RelatedResourceNotFoundError(f"Document {doc_id} not found.")

        property_id = payload.property_id
        contract_id = payload.contract_id

        if not property_id and not contract_id:
            property_id = doc.property_id
            contract_id = doc.contract_id

        if current_user:
            await self._authorize_user_to_property(
                db,
                current_user,
                property_id=property_id,
                contract_id=contract_id,
            )

        try:
            doc = await self.document_repo.update(db, doc_id, payload)
            await db.commit()
            return doc
        except Exception:
            raise

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
        """Replace the physical file behind an existing document record,
        optionally relinking it to a different property, contract, or
        tenant in the same request.

        This exists because "replace the file" and "relink it" are almost
        always the same intent from the caller's point of view — splitting
        them into two required HTTP calls (upload, then patch) would be
        pure overhead with no case where you'd want them decoupled.

        `property_id`/`contract_id`/`tenant_id` here mean "leave unchanged
        if None, set to this value if provided" — there's no way to
        explicitly clear a link through this method (unlike DocumentUpdate,
        which distinguishes "omitted" from "explicitly null" via
        exclude_unset). Use PATCH /{id} for that.

        Operation order (atomicity):
        1. Fetch the document. Return None if missing (route -> 404).
        2. Validate any newly-provided property_id/contract_id/tenant_id
            actually exist — before touching storage.
        3. Authorize against the RESOLVED target: if property_id or
            contract_id was provided (i.e. this call also reassigns the
            document), authorize against that new value — not the
            document's old one. This mirrors update_document's
            anti-reassignment-bypass fix; the same bypass would exist here
            otherwise. If neither was provided, authorize against the
            document's existing values.
        4. Upload the new file to storage — no DB write yet.
        5. Update the DB record (file fields + any relink fields
            provided). If this raises, delete the newly-uploaded storage
            object before re-raising, so it doesn't become an orphan.
        6. Commit.
        7. Best-effort delete of the OLD storage object, only if the
            filename changed. Deliberately last and non-fatal: a lingering
            old file is far less harmful than a missing new one, and by
            this point the DB record no longer references it anyway.

        Raises:
            RelatedResourceNotFoundError: a provided property_id,
                contract_id, or tenant_id doesn't exist.
            DocumentForbiddenError: current_user isn't authorized.
            DocumentUploadError: storage upload failed — DB is untouched.
        """
        doc = await self.document_repo.get_by_id(db, doc_id)
        if not doc:
            return None

        if any(x is not None for x in (payload.property_id, payload.contract_id, payload.tenant_id)):
            await self._validate_related_resources(
                db, property_id=payload.property_id, contract_id=payload.contract_id, tenant_id=payload.tenant_id
            )

        auth_property_id = payload.property_id
        auth_contract_id = payload.contract_id
        if not auth_property_id and not auth_contract_id:
            auth_property_id = doc.property_id
            auth_contract_id = doc.contract_id

        if current_user:
            await self._authorize_user_to_property(
                db, current_user, property_id=auth_property_id, contract_id=auth_contract_id
            )

        old_file_name = doc.file_name

        # Upload first — no DB write yet. _upload_to_storage only reads
        # file_name/file_type off its payload, so a SimpleNamespace avoids
        # needing a full DocumentCreate here.
        try:
            self._upload_to_storage(storage_client, payload, file_obj)
        except:
            logger.exception("Storage upload failed for %s", payload.file_name)
            raise

        try:
            # DocumentUpdate no longer carries file_name/file_type/file_url
            # (see app/schemas/document.py) — those are storage-derived and
            # intentionally not part of the public relink-only schema.
            # BaseRepository.update accepts a plain dict just as well as a
            # Pydantic model, so we use one here rather than adding a
            # second, internal-only schema just for this call site.
            updated = await self.document_repo.update(db, doc_id, payload)
            await db.commit()
        except Exception:
            self._delete_from_storage(storage_client, payload.file_name)
            raise

        if old_file_name != payload.file_name:
            self._delete_from_storage(storage_client, old_file_name)

        return updated

    async def delete_document(
        self,
        db: AsyncSession,
        doc_id: UUID,
        storage_client=None,
        current_user: User | None = None,
    ) -> Document | None:

        doc = await self.document_repo.get_by_id(db, doc_id)

        if not doc:
            raise RelatedResourceNotFoundError(f"Document {doc_id} not found.")

        if current_user:
            await self._authorize_user_to_property(
                db,
                current_user,
                property_id=doc.property_id,
                contract_id=doc.contract_id,
            )

        savepoint = await db.begin_nested()

        try:
            deleted = await self.document_repo.delete(db, doc_id)

            if deleted and storage_client is not None:
                self._delete_from_storage(storage_client, doc.file_name)

            await savepoint.commit()
            await db.commit()
            return deleted
        except DocumentDeletionError as exc:
            await savepoint.rollback()
            raise DocumentDeletionError(f"Document delete rolled back: {exc}") from exc
        except Exception:
            await savepoint.rollback()
            raise

    async def get_by_contract(self, db: AsyncSession, contract_id: UUID) -> list[Document]:
        return await self.document_repo.get_by_contract(db, contract_id)

    async def get_by_property(self, db: AsyncSession, property_id: UUID) -> list[Document]:
        return await self.document_repo.get_by_property(db, property_id)

    async def get_by_tenant(self, db: AsyncSession, tenant_id: UUID) -> list[Document]:
        return await self.document_repo.get_by_tenant(db, tenant_id)

    async def get_by_type(self, db: AsyncSession, file_type: str) -> list[Document]:
        return await self.document_repo.get_by_type(db, file_type)

    async def _resolve_property(
        self,
        db: AsyncSession,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
    ) -> Property | None:
        """
        Resolve the Property a document operation is acting on.

        Resolution order:
        1. `property_id`, if provided -> direct lookup
        2. otherwise, if `contract_id` is provided, lookup the contract,
           then lookup property using `contract.property_id`.
        3. otherwise `None`
        """

        if property_id is not None:
            prop = await self._get_property(db, property_id)
            if prop is None:
                raise RelatedResourceNotFoundError(f"Property {property_id} not found.")
            return prop

        if contract_id is not None:
            contract = await self._get_contract(db, contract_id)
            if contract is None:
                raise RelatedResourceNotFoundError(f"Contract {contract_id} not found.")
            prop = await self._get_property(db, contract.property_id)
            if prop is None:
                raise RelatedResourceNotFoundError(f"Property {contract.property_id} not found.")
            return prop

        return None

    async def _authorize_user_to_property(
        self,
        db: AsyncSession,
        current_user: User,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
    ) -> None:
        """
        Enforce manager-ownership authorization for a document operation.

        - Admins are always authorized; this method is a no-op for them.
        - Non-manager, non-admin roles are not handled here — route-level
          role gating (`require_manager_or_above`) already excludes them
          from reaching mutating document endpoints at all.
        - Managers must own the resolved property (directly, or via its
          contract). If the operation targets no property/contract at all,
          managers are forbidden — only admins may operate on unattached
          documents.

        Raises:
            RelatedResourceNotFoundError: bubled up from `_resolve_property` when
                a provided property_id/contract_id doesn't exist.
            DocumentForbiddenError: when a manager isn't authorized
        """

        if getattr(current_user, "role", None) != UserRole.MANAGER:
            return

        prop = await self._resolve_property(db, property_id=property_id, contract_id=contract_id)

        if not prop:
            raise DocumentForbiddenError("User not authorized to manage this document.")

        if prop.manager_id != current_user.id:
            raise DocumentForbiddenError("User not authorized to manage this document.")

    async def _validate_related_resources(
        self,
        db: AsyncSession,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
        tenant_id: UUID | None,
    ) -> None:
        """Validate that any provided property_id, contract_id, or
        tenant_id actually exists, independent of authorization.

        This exists separately from `_resolve_property` because `tenant_id`
        has no bearing on property resolution or manager authorization at
        all — a document can be tenant-linked with no property or contract
        in play, and that link still needs existence-checking on its own.

        Built on the same `_get_property`/`_get_contract`/`_get_tenant`
        primitives `_resolve_property` uses, so "how to fetch X" stays
        defined in exactly one place. Callers combining this with
        `_authorize_user_to_property`/`_resolve_property` will still issue a
        duplicate query for property_id/contract_id when both run for the
        same request (e.g. `create_document` will, once migrated) — that's
        a call-pattern cost, not a logic-duplication one, and is worth
        revisiting once real call sites exist rather than optimizing
        speculatively now.

        Raises:
            RelatedResourceNotFoundError: for the first of property_id,
                contract_id, or tenant_id (checked in that order) that is
                provided but doesn't resolve to an existing record.
        """
        if property_id is not None:
            prop = await self._get_property(db, property_id)
            if prop is None:
                raise RelatedResourceNotFoundError(f"Property {property_id} not found.")

        if contract_id is not None:
            contract = await self._get_contract(db, contract_id)
            if contract is None:
                raise RelatedResourceNotFoundError(f"Contract {contract_id} not found.")

        if tenant_id is not None:
            tenant = await self._get_tenant(db, tenant_id)
            if tenant is None:
                raise RelatedResourceNotFoundError(f"Tenant {tenant_id} not found.")

    def build_object_url(self, file_name: str) -> str:
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
        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned. storage object after DB write failure: {file_name}")
            raise DocumentDeletionError(f"File deletion failed: {e}")
