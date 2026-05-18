import uuid

from pydantic import BaseModel, EmailStr
from datetime import datetime
from app.models.user import UserRole
from app.schemas.base import BaseResponse


# ─── Base ─────────────────────────────────────────────────
class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    role: UserRole = UserRole.USER
    is_active: bool = True


# ─── Create ───────────────────────────────────────────────
class UserCreate(UserBase):
    """Used when creating a new user — request body."""

    password: str  # Plain password, will be hashed in the service layer


# ─── Update ───────────────────────────────────────────────
class UserUpdate(BaseModel):
    """All fields optional — only send what you want to change."""

    full_name: str | None = None
    username: str | None = None
    email: EmailStr | None = None
    password: str | None = None  # Plain password, will be hashed if provided
    role: UserRole | None = None
    is_active: bool | None = None


# ─── Login ───────────────────────────────────────────────
class UserLogin(BaseModel):
    """Used for login requests."""

    identifier: str  # username or email
    password: str


# ─── Token Response ─────────────────────────────────────
class TokenResponse(BaseModel):
    """Returned after successful login."""

    access_token: str
    token_type: str = "bearer"


# ─── Response ─────────────────────────────────────────────
class UserResponse(UserBase, BaseResponse):
    """Returned to the client — includes DB-generated fields."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
