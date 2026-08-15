import uuid

from pydantic import BaseModel
from datetime import datetime

from app.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class CollectionBase(BaseModel):
    name: str
    description: str | None = None
    property_id: uuid.UUID
    contract_id: uuid.UUID | None = None


# ─── Create ───────────────────────────────────────────────
class CollectionCreate(CollectionBase):
    """Used when creating a new collection — request body."""

    pass


# ─── Update ───────────────────────────────────────────────
class CollectionUpdate(BaseModel):
    """All fields optional — only send what you want to change.

    `property_id` is intentionally absent: a collection's owning property
    is fixed at creation, mirroring `ContractUpdate`'s immutable
    `property_id`. `contract_id` may still be narrowed, widened back to
    `None`, or changed to a different contract on the same property.
    """

    name: str | None = None
    description: str | None = None
    contract_id: uuid.UUID | None = None


# ─── Response ─────────────────────────────────────────────
class CollectionResponse(CollectionBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
