import uuid

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.security import hash_password
from app.models.billing_record import BillingRecord, BillingRecordStatus
from app.models.collection import Collection
from app.leasing.models.contract import Contract, RentalType as ContractRentalType
from app.models.document import Document
from app.leasing.models.lease import BillingCycle, Lease, RenewalOption
from app.models.payment import Payment
from app.properties.models.property import Property, PropertyStatus
from app.models.receipt import Receipt
from app.crm.models.tenant import Tenant
from app.identity.models.user import User, UserRole


def make_property(
    name: str | None = None,
    address: str | None = None,
    description: str | None = "A test property",
    status: PropertyStatus = PropertyStatus.vacant,
    manager_id: uuid.UUID | None = None,
) -> dict:
    """Returns a dict matching PropertyCreate schema."""
    suffix = uuid.uuid4().hex[:8]
    return {
        "name": name or f"Test Property {suffix}",
        "address": address or f"Test address {suffix}",
        "description": description,
        "status": status.value,
        "manager_id": manager_id,
    }


async def make_property_model(db, **kwargs) -> Property:
    """Creates and persists a Property directly in the test DB."""
    data = make_property(**kwargs)
    obj = Property(
        id=uuid.uuid4(),
        **{k: v for k, v in data.items()},
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
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


async def make_user_model(db, **kwargs) -> User:
    """Creates and persists a User directly in the test DB (with hashed password)."""
    data = make_user(**kwargs)
    data["email"] = data["email"].strip().lower()
    data["username"] = data["username"].strip().lower()
    plain_password = data.pop("password")
    obj = User(
        id=uuid.uuid4(),
        password_hash=hash_password(plain_password),
        **data,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def make_admin_model(db, **kwargs) -> User:
    """Shortcut to create an admin user in the test DB."""
    defaults = {
        "full_name": "Admin User",
        "username": "adminuser",
        "email": "admin@example.com",
        "role": UserRole.ADMIN,
    }
    defaults.update(kwargs)
    return await make_user_model(db, **defaults)


async def make_manager_model(db, **kwargs) -> User:
    """Shortcut to create a manager user in the test DB."""
    defaults = {
        "full_name": "Manager User",
        "username": "mgruser",
        "email": "mgr@example.com",
        "role": UserRole.MANAGER,
    }
    defaults.update(kwargs)
    return await make_user_model(db, **defaults)


def make_admin() -> SimpleNamespace:
    """
    Lightweight admin stand-in for service unit tests that mock the DB
    session (`mock_db`) rather than hitting a real one.

    Unlike `make_admin_model`, this is NOT persisted — it's a bare
    `SimpleNamespace(id, role)`, just enough duck-typing for
    `ResourceAuthorizationMixin._authorize_user_to_property` to read
    `.id`/`.role` off it. Use `make_admin_model` instead for anything that
    goes through a real `db` session or the `client`/`db` fixtures.
    """
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)


def make_manager(manager_id: uuid.UUID | None = None) -> SimpleNamespace:
    """
    Lightweight manager stand-in — see `make_admin`'s docstring for why
    this isn't a persisted model. `manager_id` lets a test pin the id to
    match a fake `Property.manager_id`, to exercise the
    owns-this-property vs. doesn't-own-it branches in
    `_authorize_user_to_property`.
    """
    return SimpleNamespace(id=manager_id or uuid.uuid4(), role=UserRole.MANAGER)


def make_regular_user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    """
    Lightweight USER-role stand-in - see `make_admin`'s docstring for why
    this isn't a persisted model. Used to prove authorization checks fail closed for roles
    other than ADMIN/MANAGER instead of silently treating them as authorized.
    """
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=UserRole.USER)


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


async def make_tenant_model(db, user_id: uuid.UUID | None = None, **kwargs) -> Tenant:
    """Creates and persists a Tenant directly in the test DB.

    `user_id` is kept out of `make_tenant()` (which mirrors TenantCreate,
    a request-body schema with no user_id field) and applied directly to
    the model instead, since portal linkage happens via
    TenantService.link_user, not tenant creation.
    """
    data = make_tenant(**kwargs)
    data["email"] = data["email"].strip().lower()
    obj = Tenant(id=uuid.uuid4(), user_id=user_id, **data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
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


async def make_contract_model(db, property_id: uuid.UUID, tenant_id: uuid.UUID, **kwargs) -> Contract:
    """
    Creates and persists a Contract directly in the test DB.
    Requires pre-existing property and tenant IDs (FK constraints).
    """
    data = make_contract(property_id=property_id, tenant_id=tenant_id, **kwargs)
    obj = Contract(id=uuid.uuid4(), **data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


def make_document(
    file_name: str = "test_document.pdf",
    file_type: str = "application/pdf",
    contract_id: uuid.UUID | None = None,
    property_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
) -> dict:
    """Returns a dict matching the public DocumentCreate schema."""
    return {
        "file_name": file_name,
        "file_type": file_type,
        "contract_id": contract_id,
        "property_id": property_id,
        "tenant_id": tenant_id,
        "collection_id": collection_id,
    }


async def make_document_model(db, file_url: str = "http://example.com/test_document.pdf", **kwargs) -> Document:
    """Creates and persists a Document directly in the test DB."""
    data = make_document(**kwargs)
    obj = Document(
        id=uuid.uuid4(),
        file_url=file_url,
        **data,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ─── Receipt ──────────────────────────────────────────────────────────────────


async def make_receipt_model(db, payment_id: uuid.UUID, document_id: uuid.UUID, **kwargs) -> Receipt:
    """Creates and persists a Receipt directly in the test DB.

    `receipt_number` is never set here — it's a server-side Identity
    column, and letting Postgres assign it is the entire point of the
    race-safe numbering scheme under test.
    """
    obj = Receipt(id=uuid.uuid4(), payment_id=payment_id, document_id=document_id, **kwargs)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ─── Payment ──────────────────────────────────────────────────────────────────


def make_payment(
    contract_id: uuid.UUID | None = None,
    billing_record_id: uuid.UUID | None = None,
    amount: float = 15000.00,
    paid_at: datetime | None = None,
    payment_method: str | None = "cash",
    status: str = "PAID",
    reference_number: str | None = None,
) -> dict:
    """Returns a dict matching PaymentCreate schema."""
    return {
        "contract_id": contract_id,
        "billing_record_id": billing_record_id,
        "amount": amount,
        "paid_at": paid_at or datetime.now(timezone.utc),
        "payment_method": payment_method,
        "status": status,
        "reference_number": reference_number,
    }


async def make_payment_model(db, contract_id: uuid.UUID, **kwargs) -> Payment:
    """
    Creates and persists a Payment directly in the test DB.
    Requires a pre-existing contract id (FK constraint).
    """
    data = make_payment(contract_id=contract_id, **kwargs)
    obj = Payment(id=uuid.uuid4(), **data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ─── Collection ───────────────────────────────────────────────────────────────


def make_collection(
    property_id: uuid.UUID | None = None,
    contract_id: uuid.UUID | None = None,
    name: str = "Test Collection",
    description: str | None = "A test collection",
) -> dict:
    """Returns a dict matching CollectionCreate schema."""
    return {
        "name": name,
        "description": description,
        "property_id": property_id,
        "contract_id": contract_id,
    }


async def make_collection_model(db, property_id: uuid.UUID, **kwargs) -> Collection:
    """
    Creates and persists a Collection directly in the test DB.
    Requires a pre-existing property id (FK constraint).
    """
    data = make_collection(property_id=property_id, **kwargs)
    obj = Collection(id=uuid.uuid4(), **data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ─── Lease ────────────────────────────────────────────────────────────────────


def make_lease(
    contract_id: uuid.UUID | None = None,
    monthly_rent: float = 15000.00,
    due_day: int = 5,
    billing_cycle: BillingCycle = BillingCycle.monthly,
    security_deposit: float | None = 15000.00,
    advance_payment: float | None = None,
    late_fee_amount: float | None = 500.00,
    late_fee_percent: float | None = None,
    grace_period_days: int = 3,
    renewal_option: RenewalOption = RenewalOption.none,
    status: str = "ACTIVE",
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Returns a dict matching LeaseCreate schema."""
    _start = start_date or date.today()
    return {
        "contract_id": contract_id,
        "monthly_rent": monthly_rent,
        "due_day": due_day,
        "billing_cycle": billing_cycle.value,
        "security_deposit": security_deposit,
        "advance_payment": advance_payment,
        "late_fee_amount": late_fee_amount,
        "late_fee_percent": late_fee_percent,
        "grace_period_days": grace_period_days,
        "renewal_option": renewal_option.value,
        "status": status,
        "start_date": _start,
        "end_date": end_date,
    }


async def make_lease_model(db, contract_id: uuid.UUID, **kwargs) -> Lease:
    """
    Creates and persists a Lease directly in the test DB.
    Requires a pre-existing contract id (FK constraint).
    """
    data = make_lease(contract_id=contract_id, **kwargs)
    obj = Lease(id=uuid.uuid4(), **data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


# ─── BillingRecord ────────────────────────────────────────────────────────────


def make_billing_record(
    lease_id: uuid.UUID | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    due_date: date | None = None,
    amount_due: float = 15000.00,
    late_fee_applied: bool = False,
    late_fee_amount_charged: float | None = None,
    status: str = BillingRecordStatus.pending.value,
) -> dict:
    """Returns a dict matching BillingRecordCreate schema."""
    _period_start = period_start or date.today().replace(day=1)
    _period_end = period_end or (
        date(_period_start.year, _period_start.month + 1, 1) - timedelta(days=1)
        if _period_start.month < 12
        else date(_period_start.year, 12, 31)
    )
    _due_date = due_date or _period_start.replace(day=min(5, _period_end.day))
    return {
        "lease_id": lease_id,
        "period_start": _period_start,
        "period_end": _period_end,
        "due_date": _due_date,
        "amount_due": amount_due,
        "late_fee_applied": late_fee_applied,
        "late_fee_amount_charged": late_fee_amount_charged,
        "status": status,
    }


async def make_billing_record_model(db, lease_id: uuid.UUID, **kwargs) -> BillingRecord:
    """
    Creates and persists a BillingRecord directly in the test DB.
    Requires a pre-existing lease id (FK constraint).
    """
    data = make_billing_record(lease_id=lease_id, **kwargs)
    obj = BillingRecord(id=uuid.uuid4(), **data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj
