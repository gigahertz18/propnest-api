import uuid

from pydantic import BaseModel
from datetime import datetime

from app.models.property import PropertyStatus
from app.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class PropertyBase(BaseModel):
    name: str
    address: str
    description: str | None = None
    status: PropertyStatus = PropertyStatus.vacant


# ─── Create ───────────────────────────────────────────────
class PropertyCreate(PropertyBase):
    """Used when creating a new property — request body."""

    pass


# ─── Update ───────────────────────────────────────────────
class PropertyUpdate(BaseModel):
    """All fields optional — only send what you want to change."""

    name: str | None = None
    address: str | None = None
    description: str | None = None
    status: PropertyStatus | None = None
    is_active: bool | None = None


# ─── Response ─────────────────────────────────────────────
class PropertyResponse(PropertyBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    is_active: bool
    manager_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
