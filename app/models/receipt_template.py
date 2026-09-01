import uuid
from sqlalchemy import Boolean, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.core.models.base import TimestampMixin


class ReceiptTemplate(Base, TimestampMixin):
    __tablename__ = "receipt_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # NULL = the global default template — used for any property that has
    # no active template of its own. Only one row may be active per scope
    # (a specific property_id, or globally when NULL) — enforced by the
    # partial unique index below, not just app logic.
    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"), nullable=True, index=True)

    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # One active template per scope. A plain unique index on
        # property_id can't cover the property_id IS NULL (global) case —
        # Postgres treats NULLs as distinct, so multiple NULL rows would
        # never collide — so this coalesces to a sentinel UUID for the
        # global scope: every active global row indexes to the same
        # constant value, so a second one collides exactly like a second
        # active row for the same real property_id would.
        Index(
            "uq_active_receipt_template_scope",
            text("COALESCE(property_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ReceiptTemplate id={self.id} name={self.name} "
            f"property_id={self.property_id} is_active={self.is_active}>"
        )
