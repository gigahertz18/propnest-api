# tests/fixtures/auth.py
import pytest_asyncio

from dataclasses import dataclass

from app.models.user import User, UserRole
from tests.factories import make_user_model

@dataclass
class AuthContext:
    user: User
    token: str
    headers: dict[str, str]

async def login(client, identifier: str, password: str = "password123") -> str:
    """Returns a bearer token for the given identifier."""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "identifier": identifier,
            "password": password,
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def create_authenticated_user(client, db):
    async def _create_user_and_token(
        *,
        username: str = "user1",
        full_name: str = "User1",
        email: str = "user1@example.com",
        role: UserRole = UserRole.USER,
        password: str = "password123",
    ):
        user = await make_user_model(
            db,
            username=username,
            email=email,
            role=role,
            password=password,
        )
        
        token = await login(client, username, password=password)
        return AuthContext(user, token, auth_headers(token))
    
    return _create_user_and_token

@pytest_asyncio.fixture
async def authenticate_admin(create_authenticated_user):
    async def _create(**kwargs):
        kwargs.setdefault("username", "adminuser")
        kwargs.setdefault("email", "adminuser@example.com")
        kwargs.setdefault("full_name", "Admin User")
        kwargs.setdefault("role", UserRole.ADMIN)
        return await create_authenticated_user(**kwargs)
    
    return _create

@pytest_asyncio.fixture
async def authenticate_manager(create_authenticated_user):
    async def _create(**kwargs):
        kwargs.setdefault("username", "manager1")
        kwargs.setdefault("email", "manager1@example.com")
        kwargs.setdefault("full_name", "Manager User")
        kwargs.setdefault("role", UserRole.MANAGER)
        return await create_authenticated_user(**kwargs)
    
    return _create

@pytest_asyncio.fixture
async def authenticate_user(create_authenticated_user):
    async def _create(**kwargs):
        return await create_authenticated_user(**kwargs)
    return _create
