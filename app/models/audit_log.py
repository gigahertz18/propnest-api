import enum
import uuid

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class AuditLog(Base):
    """
    Immutable record of a mutation performed by a mutating service method.
    No `updated_at` — audit rows are append-only and never modified.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Nullable + ON DELETE SET NULL: an audit row must outlive the actor's
    # account (deleting a user must never be blocked by, or erase, the
    # trail of what they did) — mirrors Tenant.user_id's SET NULL pattern.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction), nullable=False)

    # Polymorphic by design — no FK, since one column can't reference every
    # mutable entity table. entity_type is the model name (e.g. "Property").
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action} "
            f"entity_type={self.entity_type} entity_id={self.entity_id}>"
        )
