import uuid
from sqlalchemy.orm import Session

from app.repositories.base import BaseRepository
from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentUpdate 



class DocumentRepository(BaseRepository[Document, DocumentCreate, DocumentUpdate]):
    """
    Document-specific queries on top of the generic BaseRepository.
    get_all, get_by_id, create, update, delete are inherited — don't repeat them.
    """

    def get_by_contract(
        self,
        db: Session,
        contract_id: uuid.UUID,
    ) -> list[Document]:
        """Return all documents linked to a given contract."""
        return (
            db.query(self.model)
            .filter(self.model.contract_id == contract_id)
            .all()
        )

    def get_by_property(
        self,
        db: Session,
        property_id: uuid.UUID,
    ) -> list[Document]:
        """Return all documents linked to a given property."""
        return (
            db.query(self.model)
            .filter(self.model.property_id == property_id)
            .all()
        )
    
    def get_by_tenant(
        self,
        db: Session,
        tenant_id: uuid.UUID,
    ) -> list[Document]:
        """Return all documents linked to a given tenant."""
        return (
            db.query(self.model)
            .filter(self.model.tenant_id == tenant_id)
            .all()
        )
    
    def get_by_type(
        self,
        db: Session,
        file_type: str,
    ) -> list[Document]:
        """Return all documents of a given type (e.g. LEASE_AGREEMENT, ID_PROOF)."""
        return (
            db.query(self.model)
            .filter(self.model.file_type == file_type)
            .all()
        )


# Instantiate once — import this instance everywhere
document_repo = DocumentRepository(Document)
