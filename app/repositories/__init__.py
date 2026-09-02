from app.properties.repositories.property import property_repo
from app.identity.repositories.user import user_repo
from app.leasing.repositories.contract import contract_repo
from app.documents.repositories.document import document_repo
from app.repositories.payment import payment_repo
from app.crm.repositories.tenant import tenant_repo

__all__ = [
    "property_repo",
    "user_repo",
    "contract_repo",
    "document_repo",
    "tenant_repo",
    "payment_repo",
]
