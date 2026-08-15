import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class Collection(Base, TimestampMixin):
    """
    A named grouping of Documents, scoped to a Property (required) and
    optionally narrowed to one of that property's Contracts. First
    organizational layer above the flat per-entity Document list — see
    issue #83.
    """

    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), nullable=False, index=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<Collection id={self.id} name={self.name} property_id={self.property_id}>"
