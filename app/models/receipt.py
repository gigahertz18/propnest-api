import uuid
from sqlalchemy import ForeignKey, Identity, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Server-side Postgres sequence (via Identity) — race-safe under
    # concurrent payment recording, unlike an app-level max()+1 scheme.
    receipt_number: Mapped[int] = mapped_column(
        Integer,
        Identity(start=1, increment=1),
        unique=True,
        nullable=False,
        index=True,
    )

    # Not unique: multiple Receipt rows may reference the same payment
    # (reprints) — that's the whole point of the append-only design.
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)

    # Unique: each Receipt owns exactly one generated PDF Document; a
    # reprint always renders and stores a brand-new Document too, never
    # re-links an existing one.
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True)

    def __repr__(self) -> str:
        return (
            f"<Receipt id={self.id} receipt_number={self.receipt_number} "
            f"payment_id={self.payment_id} document_id={self.document_id}>"
        )
