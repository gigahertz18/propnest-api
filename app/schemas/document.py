import uuid

from pydantic import BaseModel
from datetime import datetime

from app.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class DocumentBase(BaseModel):
    file_name: str
    file_type: str
    file_url: str
    contract_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None


# ─── Create ───────────────────────────────────────────────
class DocumentCreate(DocumentBase):
    """Used when creating a new document — request body."""

    pass


# ─── Update ───────────────────────────────────────────────
class DocumentUpdate(BaseModel):
    """All fields optional — only send what you want to change."""

    file_name: str | None = None
    file_type: str | None = None
    file_url: str | None = None
    contract_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None


# ─── Response ─────────────────────────────────────────────
class DocumentResponse(DocumentBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
