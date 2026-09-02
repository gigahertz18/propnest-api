import uuid

from pydantic import BaseModel, Field
from datetime import datetime

from app.properties.models.property import PropertyStatus
from app.core.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class PropertyBase(BaseModel):
    name: str
    address: str
    description: str | None = Field(default=None, description="Free-text notes about the property.")
    status: PropertyStatus = Field(
        default=PropertyStatus.vacant,
        description="Current occupancy status; set automatically by contract lifecycle events.",
    )


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


# ─── Assign Manager ───────────────────────────────────────
class PropertyAssignManager(BaseModel):
    """Request body for assigning a manager to a property.

    Admin-only, at the route layer. There is no corresponding unassign —
    a property keeps its last-assigned manager between contracts and gets
    reassigned (overwriting the previous value) the next time a new
    contract goes active.
    """

    manager_id: uuid.UUID = Field(description="User ID of the manager to assign. Must have the manager role.")
