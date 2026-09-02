import uuid

from pydantic import BaseModel
from datetime import datetime

from app.core.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class DocumentBase(BaseModel):
    file_name: str
    file_type: str
    contract_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None


# ─── Create ───────────────────────────────────────────────
class DocumentCreate(DocumentBase):
    """Used when creating a new document — request body."""

    pass


# ─── Update ───────────────────────────────────────────────
class DocumentRelinkUpdate(BaseModel):
    """All fields optional — only send what you want to change."""

    contract_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None


class DocumentFileUpdate(DocumentBase):
    """Used when replacing the file behind an existing document"""

    pass


# ─── Response ─────────────────────────────────────────────
class DocumentResponse(DocumentBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    file_url: str
    created_at: datetime
    updated_at: datetime
