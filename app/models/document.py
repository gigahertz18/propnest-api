import uuid
from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.db.session import Base


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    file_name: Mapped[str] = mapped_column(String)
    file_url: Mapped[str] = mapped_column(String)
    file_type: Mapped[str] = mapped_column(String)

    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)

    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"), nullable=True)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<Document id={self.id} file_name={self.file_name} contract_id={self.contract_id} property_id={self.property_id} tenant_id={self.tenant_id}>"
