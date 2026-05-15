import enum
import uuid

from sqlalchemy import String, Text, Enum, CheckConstraint, Uuid

from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.models.base import TimestampMixin


class RentalType(str, enum.Enum):
    long_term = "long_term"
    short_term = "short_term"


class PropertyStatus(str, enum.Enum):
    vacant = "vacant"
    occupied = "occupied"


# Listing platforms as a constant — easy to extend without a native enum migration
LISTING_PLATFORMS = ("direct", "airbnb", "booking", "agoda")


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

    rental_type: Mapped[RentalType] = mapped_column(
        Enum(RentalType),
        nullable=False,
    )
    listing_platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="direct",
    )
    status: Mapped[PropertyStatus] = mapped_column(
        Enum(PropertyStatus),
        nullable=False,
        default=PropertyStatus.vacant,
    )

    __table_args__ = (
        CheckConstraint(
            f"listing_platform IN {LISTING_PLATFORMS}",
            name="ck_property_listing_platform",
        ),
    )

    def __repr__(self) -> str:
        return f"<Property id={self.id} name={self.name} type={self.rental_type} platform={self.listing_platform}>"
