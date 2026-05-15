import uuid

from pydantic import BaseModel
from datetime import datetime
from app.models.property import RentalType, PropertyStatus


# ─── Base ─────────────────────────────────────────────────
class PropertyBase(BaseModel):
    name: str
    address: str
    description: str | None = None
    rental_type: RentalType
    listing_platform: str = "direct"
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
    rental_type: RentalType | None = None
    listing_platform: str | None = None
    status: PropertyStatus | None = None


# ─── Response ─────────────────────────────────────────────
class PropertyResponse(PropertyBase):
    """Rrned to the client — includes DB-generated fields."""
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}  # Allows reading from SQLAlchemy model
