
import enum
import uuid

from app.db.session import Base
from app.models.base import TimestampMixin

from sqlalchemy import String, Enum, Boolean, Uuid
from sqlalchemy.orm import Mapped, mapped_column

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True,)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True,)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False,)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False,)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        nullable=False,
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username} role={self.role} is_active={self.is_active}>"
