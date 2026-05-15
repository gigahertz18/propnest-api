import uuid

from app.models.property import Property, PropertyStatus
from app.models.user import User, UserRole
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
        id=str(uuid.uuid4()),
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
