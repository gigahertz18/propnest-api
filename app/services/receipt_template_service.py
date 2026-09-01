from __future__ import annotations

import logging

from collections.abc import Sequence
from io import BytesIO
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.models.audit_log import AuditAction
from app.models.receipt_template import ReceiptTemplate
from app.models.user import User, UserRole
from app.repositories.property import PropertyRepository
from app.repositories.receipt_template import ReceiptTemplateRepository
from app.core.services.audit import write_audit_log
from app.core.services.base import ResourceAuthorizationMixin
from app.core.services.exceptions import (
    ReceiptTemplateForbiddenError,
    ReceiptTemplateUploadError,
    ReceiptTemplateValidationError,
    RelatedResourceNotFoundError,
)
from app.services.receipt_pdf import load_default_template

logger = logging.getLogger(__name__)

# Templates are small, hand-authored HTML files, not general document
# uploads — this cap only exists to bound how much a request will spool
# into memory, not to accommodate large binary content.
_MAX_TEMPLATE_SIZE = 512 * 1024
_TEMPLATE_STORAGE_PREFIX = "receipt_templates"


class ReceiptTemplateService(ResourceAuthorizationMixin):
    """Business logic for `ReceiptTemplate` entities.

    A template's HTML is stored directly via the MinIO client (not through
    DocumentService/the generic `Document` model) — DocumentService's MIME
    allowlist is sniffed from binary magic bytes (PDF/PNG/JPEG/Word), which
    has no equivalent reliable signature for arbitrary HTML, and folding
    templates into the general Documents listing would mix print templates
    into every other document-browsing view. Only ADMIN/MANAGER can reach
    this service at all (`require_manager_or_above` at the route layer);
    property-scoped templates additionally require owning that property,
    and the global (property_id=None) template is ADMIN-only.
    """

    forbidden_error = ReceiptTemplateForbiddenError

    def __init__(
        self,
        receipt_template_repo: ReceiptTemplateRepository,
        property_repo: PropertyRepository | None = None,
    ) -> None:
        self.receipt_template_repo = receipt_template_repo
        self.property_repo = property_repo

    async def upload_template(
        self,
        db: AsyncSession,
        name: str,
        property_id: UUID | None,
        current_user: User,
        storage_client,
        file_obj,
    ) -> ReceiptTemplate:
        await self._authorize_template_scope(db, current_user, property_id)

        html_bytes = self._read_and_validate_html(file_obj)

        template_id = uuid4()
        storage_key = f"{_TEMPLATE_STORAGE_PREFIX}/{template_id}.html"
        file_url = self._build_object_url(storage_key)

        try:
            storage_client.put_object(
                settings.MINIO_BUCKET_NAME,
                storage_key,
                BytesIO(html_bytes),
                len(html_bytes),
                content_type="text/html",
            )
        except Exception as e:
            raise ReceiptTemplateUploadError(f"Storage upload failed: {e}") from e

        try:
            template = await self.receipt_template_repo.create(
                db,
                {
                    "id": template_id,
                    "name": name,
                    "property_id": property_id,
                    "storage_key": storage_key,
                    "file_url": file_url,
                    "is_active": False,
                },
            )
            write_audit_log(db, current_user, AuditAction.CREATE, "ReceiptTemplate", template.id)
            await db.commit()
            return template
        except Exception:
            try:
                storage_client.remove_object(settings.MINIO_BUCKET_NAME, storage_key)
            except Exception:
                logger.exception(f"Orphaned storage object {storage_key} could not be cleaned up after DB failure.")
            raise

    async def activate_template(
        self,
        db: AsyncSession,
        template_id: UUID,
        current_user: User,
    ) -> ReceiptTemplate:
        template = await self._get_template_or_404(db, template_id)
        await self._authorize_template_scope(db, current_user, template.property_id)

        current_active = (
            await self.receipt_template_repo.get_active_for_property(db, template.property_id)
            if template.property_id is not None
            else await self.receipt_template_repo.get_active_global(db)
        )
        if current_active is not None and current_active.id != template.id:
            await self.receipt_template_repo.update(db, current_active.id, {"is_active": False})

        updated = await self.receipt_template_repo.update(db, template.id, {"is_active": True})
        write_audit_log(db, current_user, AuditAction.UPDATE, "ReceiptTemplate", template.id)
        await db.commit()
        return updated

    async def list_templates(
        self,
        db: AsyncSession,
        current_user: User,
        property_id: UUID | None = None,
    ) -> Sequence[ReceiptTemplate]:
        if property_id is not None:
            await self._authorize_template_scope(db, current_user, property_id)
            return await self.receipt_template_repo.get_by_property(db, property_id)

        if getattr(current_user, "role", None) != UserRole.ADMIN:
            raise self.forbidden_error("Only admins may list every receipt template.")
        return await self.receipt_template_repo.get_all(db)

    async def get_template(self, db: AsyncSession, template_id: UUID, current_user: User) -> ReceiptTemplate:
        template = await self._get_template_or_404(db, template_id)
        await self._authorize_template_scope(db, current_user, template.property_id)
        return template

    async def resolve_active_template_html(
        self,
        db: AsyncSession,
        property_id: UUID | None,
        storage_client,
    ) -> str:
        """Which template a payment's receipt should render with: the
        property's own active template, falling back to the active global
        template, falling back to the built-in default file if neither
        exists yet."""
        template = None
        if property_id is not None:
            template = await self.receipt_template_repo.get_active_for_property(db, property_id)
        if template is None:
            template = await self.receipt_template_repo.get_active_global(db)
        if template is None:
            return load_default_template()
        return self._fetch_html(storage_client, template.storage_key)

    async def _authorize_template_scope(self, db: AsyncSession, current_user: User, property_id: UUID | None) -> None:
        if property_id is None:
            if getattr(current_user, "role", None) != UserRole.ADMIN:
                raise self.forbidden_error("Only admins may manage the global default receipt template.")
            return

        # Existence must be checked independent of role — _authorize_user_to_property
        # short-circuits for ADMIN before ever resolving the property, so an
        # admin acting on a nonexistent property_id would otherwise sail
        # through with no 404 at all.
        prop = await self._get_property(db, property_id)
        if prop is None:
            raise RelatedResourceNotFoundError(f"Property {property_id} not found.")

        await self._authorize_user_to_property(db, current_user, property_id=property_id, contract_id=None)

    async def _get_template_or_404(self, db: AsyncSession, template_id: UUID) -> ReceiptTemplate:
        template = await self.receipt_template_repo.get_by_id(db, template_id)
        if not template:
            raise RelatedResourceNotFoundError(f"ReceiptTemplate {template_id} not found.")
        return template

    def _read_and_validate_html(self, file_obj) -> bytes:
        stream = getattr(file_obj, "file", file_obj)
        data = stream.read(_MAX_TEMPLATE_SIZE + 1)
        if len(data) > _MAX_TEMPLATE_SIZE:
            raise ReceiptTemplateValidationError("Template file too large")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ReceiptTemplateValidationError("Template file must be valid UTF-8 HTML") from e
        return data

    def _fetch_html(self, storage_client, storage_key: str) -> str:
        response = storage_client.get_object(settings.MINIO_BUCKET_NAME, storage_key)
        try:
            return response.read().decode("utf-8")
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
            release_conn = getattr(response, "release_conn", None)
            if release_conn:
                release_conn()

    def _build_object_url(self, storage_key: str) -> str:
        endpoint = settings.MINIO_ENDPOINT.rstrip("/")
        bucket = settings.MINIO_BUCKET_NAME
        return f"{endpoint}/{bucket}/{storage_key}"
