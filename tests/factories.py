import uuid

from datetime import date, timedelta
from app.models.property import Property, PropertyStatus
from app.models.user import User, UserRole
from app.models.contract import Contract, RentalType as ContractRentalType
from app.models.tenants import Tenant
from app.models.document import Document
from app.core.security import hash_password


def make_property(
    name: str = "Test Property",
    address: str = "123 Test Street",
    description: str | None = "A test property",
    status: PropertyStatus = PropertyStatus.vacant,
) -> dict:
    """Returns a dict matching PropertyCreate schema."""
    return {
        "name": name,
        "address": address,
        "description": description,
        "status": status.value,
    }


def make_property_model(db, **kwargs) -> Property:
    """Creates and persists a Property directly in the test DB."""
    data = make_property(**kwargs)
    obj = Property(
        id=uuid.uuid4(),
        **{k: v for k, v in data.items()},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# User factory functions
def make_user(
    username: str = "testuser",
    email: str = "testuser@example.com",
    full_name: str = "Test User",
    password: str = "password123",
    role: UserRole = UserRole.USER,
    is_active: bool = True,
) -> dict:
    """Returns a dict matching UserCreate schema."""
    return {
        "username": username,
        "email": email,
        "full_name": full_name,
        "password": password,
        "role": role.value,
        "is_active": is_active,
    }


def make_user_model(db, **kwargs) -> User:
    """Creates and persists a User directly in the test DB (with hashed password)."""
    data = make_user(**kwargs)
    plain_password = data.pop("password")
    obj = User(
        id=uuid.uuid4(),
        password_hash=hash_password(plain_password),
        **data,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def make_admin_model(db, **kwargs) -> User:
    """Shortcut to create an admin user in the test DB."""
    defaults = {
        "full_name": "Admin User",
        "username": "adminuser",
        "email": "admin@example.com",
        "role": UserRole.ADMIN,
    }
    defaults.update(kwargs)
    return make_user_model(db, **defaults)

# ─── Tenant ───────────────────────────────────────────────────────────────────
 
def make_tenant(
    full_name: str = "Test Tenant",
    email: str = "tenant@example.com",
    date_of_birth: date = date(1990, 1, 1),
    phone_number: str = "09171234567",
    current_address: str = "456 Tenant Street",
    occupation: str | None = "Engineer",
    notes: str | None = None,
    is_active: bool = True,
) -> dict:
    """Returns a dict matching TenantCreate schema."""
    return {
        "full_name": full_name,
        "email": email,
        "phone_number": phone_number,
        "date_of_birth": date_of_birth,
        "current_address": current_address,
        "occupation": occupation,
        "notes": notes,
        "is_active": is_active,
    }
 
 
def make_tenant_model(db, **kwargs) -> Tenant:
    """Creates and persists a Tenant directly in the test DB."""
    data = make_tenant(**kwargs)
    obj = Tenant(id=uuid.uuid4(), **data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
 
 
# ─── Contract ─────────────────────────────────────────────────────────────────
 
def make_contract(
    property_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    rental_type: ContractRentalType = ContractRentalType.long_term,
    start_date: date | None = None,
    end_date: date | None = None,
    rent_amount: float = 15000.00,
    deposit: float | None = 15000.00,
    booking_source: str = "direct",
    status: str = "ACTIVE",
) -> dict:
    """Returns a dict matching ContractCreate schema."""
    _start = start_date or date.today()
    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "rental_type": rental_type.value,
        "start_date": _start,
        "end_date": end_date,
        "rent_amount": rent_amount,
        "deposit": deposit,
        "booking_source": booking_source,
        "status": status,
    }
 
 
def make_contract_model(db, property_id: uuid.UUID, tenant_id: uuid.UUID, **kwargs) -> Contract:
    """
    Creates and persists a Contract directly in the test DB.
    Requires pre-existing property and tenant IDs (FK constraints).
    """
    data = make_contract(property_id=property_id, tenant_id=tenant_id, **kwargs)
    obj = Contract(id=uuid.uuid4(), **data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def make_document(
    file_name: str = "test_document.pdf",
    file_type: str = "application/pdf",
    file_url: str = "http://example.com/test_document.pdf",
    contract_id: uuid.UUID | None = None,
    property_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> dict:
    """Returns a dict matching DocumentCreate schema."""
    return {
        "file_name": file_name,
        "file_type": file_type,
        "file_url": file_url,
        "contract_id": contract_id,
        "property_id": property_id,
        "tenant_id": tenant_id,
    }

def make_document_model(db, **kwargs) -> Document:
    """Creates and persists a Document directly in the test DB."""
    data = make_document(**kwargs)
    obj = Document(
        id=uuid.uuid4(),
        **{k: v for k, v in data.items()},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
