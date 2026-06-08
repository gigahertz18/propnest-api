import pytest
from types import SimpleNamespace

from app.main import app
from app.models.user import UserRole


@pytest.fixture
def set_override():
    """Helper to temporarily set FastAPI dependency overrides for a test.

    Usage:
        set_override(dep, provider)

    The fixture will remove any overrides set via this helper after the test.
    """
    deps = []

    def _set(dep, provider):
        app.dependency_overrides[dep] = provider
        deps.append(dep)

    yield _set

    for d in deps:
        app.dependency_overrides.pop(d, None)


@pytest.fixture
def admin_user():
    return SimpleNamespace(id=None, role=UserRole.ADMIN)


@pytest.fixture
def manager_user():
    return SimpleNamespace(id=None, role=UserRole.MANAGER)


@pytest.fixture
def simple_ns():
    return SimpleNamespace
