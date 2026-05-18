import pytest
import uuid

from app.repositories.tenant import tenant_repo
from app.schemas.tenants import TenantCreate, TenantUpdate
from app.models.tenants import Tenant
from tests.factories import make_tenant, make_tenant_model


class TestTenantRepositoryGetAll:
    def test_returns_empty_list_when_no_tenants(self, db):
        result = tenant_repo.get_all(db)
        assert result == []

    def test_returns_all_tenants(self, db):
        make_tenant_model(db, full_name="Tenant A")
        make_tenant_model(db, full_name="Tenant B")
        result = tenant_repo.get_all(db)
        assert len(result) == 2

    def test_skip_and_limit(self, db):
        for i in range(5):
            make_tenant_model(db, full_name=f"Tenant {i}")
        result = tenant_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2
        
class TestTenantRepositoryGetById:
    def test_returns_tenant_when_found(self, db):
        tenant = make_tenant_model(db)
        result = tenant_repo.get_by_id(db, tenant.id)
        assert result is not None
        assert result.id == tenant.id

    def test_returns_none_when_not_found(self, db):
        result = tenant_repo.get_by_id(db, uuid.uuid4())
        assert result is None

class TestTenantRepositoryCreate:
    def test_creates_tenant_successfully(self, db):
        payload = TenantCreate(**make_tenant())
        result = tenant_repo.create(db, payload)
        assert result.id is not None
        assert result.full_name == "Test User"
        assert result.email == "testuser@example.com"
    
    def test_created_tenant_is_persisted(self, db):
        payload = TenantCreate(**make_tenant(full_name="Persisted Tenant"))
        created = tenant_repo.create(db, payload)
        fetched = tenant_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.full_name == "Persisted Tenant"
    
