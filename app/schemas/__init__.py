from app.schemas.base import BaseResponse, PaginatedResponse
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyResponse
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserLogin, TokenResponse
from app.schemas.contract import ContractCreate, ContractUpdate, ContractResponse
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate, DocumentResponse
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantResponse, TenantLinkUser

__all__ = [
    "BaseResponse",
    "PaginatedResponse",
    "PropertyCreate",
    "PropertyUpdate",
    "PropertyResponse",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserLogin",
    "TokenResponse",
    "ContractCreate",
    "ContractUpdate",
    "ContractResponse",
    "DocumentCreate",
    "DocumentRelinkUpdate",
    "DocumentFileUpdate",
    "DocumentResponse",
    "TenantCreate",
    "TenantUpdate",
    "TenantResponse",
    "TenantLinkUser",
]
