import enum
import uuid

from sqlalchemy import String, Text, Enum, Uuid, Boolean, ForeignKey

from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.models.base import TimestampMixin


class PropertyStatus(str, enum.Enum):
    vacant = "vacant"
    occupied = "occupied"


class Property(Base, TimestampMixin):
    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional manager ownership — a manager user may be assigned to a property
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[PropertyStatus] = mapped_column(
        Enum(PropertyStatus),
        nullable=False,
        default=PropertyStatus.vacant,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    def __repr__(self) -> str:
        return f"<Property id={self.id} name={self.name} status={self.status} is_active={self.is_active}>"
