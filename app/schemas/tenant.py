import uuid

from pydantic import BaseModel
from datetime import datetime, date

from app.schemas.base import BaseResponse


class TenantBase(BaseModel):
    full_name: str
    email: str
    phone_number: str
    date_of_birth: date
    current_address: str
    occupation: str | None = None
    notes: str | None = None
    is_active: bool = True


class TenantCreate(TenantBase):
    """Used when creating a new tenant — request body."""

    pass


class TenantUpdate(BaseModel):
    """All fields optional — only send what you want to change."""

    full_name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    date_of_birth: date | None = None
    current_address: str | None = None
    occupation: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class TenantResponse(TenantBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class TenantLinkUser(BaseModel):
    """Request body for linking a tenant to a portal-access User account."""

    user_id: uuid.UUID
