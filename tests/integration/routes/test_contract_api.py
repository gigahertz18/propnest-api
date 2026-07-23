import pytest
import uuid

from app.models.user import UserRole
from tests.factories import (
    make_user_model,
    make_contract_model,
    make_property_model,
    make_tenant_model,
    make_payment_model,
    make_document_model,
)


@pytest.mark.asyncio
class TestListContractRoute:
    async def test_returns_empty_list(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/contracts/", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_returns_all_contracts(self, client, db, authenticate_admin):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        for status in ("ACTIVE", "EXPIRED", "TERMINATED", "CANCELLED"):
            await make_contract_model(db, prop.id, tenant.id, status=status)

        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/contracts/", headers=auth_ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 4
        assert len(resp_data["items"]) == 4

    async def test_total_stays_full_on_second_page(self, client, db, authenticate_admin):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        for status in ("ACTIVE", "EXPIRED", "TERMINATED", "CANCELLED"):
            await make_contract_model(db, prop.id, tenant.id, status=status)

        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/contracts/?skip=2&limit=2", headers=auth_ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 4
        assert len(resp_data["items"]) == 2


@pytest.mark.asyncio
class TestGetContractRoute:
    async def test_returns_contract_by_id(self, client, db, authenticate_admin):

        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        response = await client.get(f"/api/v1/contracts/{contract.id}", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(contract.id)

    async def test_returns_404_when_not_found(self, client, authenticate_admin):

        auth_ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/contracts/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
class TestCreateContractRoute:
    async def test_manager_forbidden_for_unmanaged_property(self, client, db, authenticate_manager):
        """Managers may only create contracts for properties they manage."""
        mgr1_ctx = await authenticate_manager(username="mgr1", email="mgr1@example.com")
        mgr2 = await make_user_model(db, username="mgr2", email="mgr2@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr2.id)

        payload = {
            "property_id": str(prop.id),
            "tenant_id": str(tenant.id),
            "rental_type": "long_term",
            "start_date": "2026-01-01",
            "end_date": None,
            "rent_amount": 1000.0,
            "deposit": 500.0,
            "booking_source": "direct",
            "status": "ACTIVE",
        }

        response = await client.post("/api/v1/contracts/", json=payload, headers=mgr1_ctx.headers)
        assert response.status_code == 403

    async def test_manager_can_create_for_owned_property(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)

        payload = {
            "property_id": str(prop.id),
            "tenant_id": str(tenant.id),
            "rental_type": "long_term",
            "start_date": "2026-01-01",
            "end_date": None,
            "rent_amount": 1000.0,
            "deposit": 500.0,
            "booking_source": "direct",
            "status": "ACTIVE",
        }

        response = await client.post("/api/v1/contracts/", json=payload, headers=mgr_ctx.headers)
        assert response.status_code == 201

    async def test_returns_409_when_property_already_has_active_contract(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant1 = await make_tenant_model(db, email="t1@example.com")
        tenant2 = await make_tenant_model(db, email="t2@example.com")
        await make_contract_model(db, prop.id, tenant1.id, status="ACTIVE")

        payload = {
            "property_id": str(prop.id),
            "tenant_id": str(tenant2.id),
            "rental_type": "long_term",
            "start_date": "2026-01-01",
            "end_date": None,
            "rent_amount": 1000.0,
            "deposit": 500.0,
            "booking_source": "direct",
            "status": "ACTIVE",
        }

        response = await client.post("/api/v1/contracts/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 409


@pytest.mark.asyncio
class TestUpdateContractRoute:
    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.patch(f"/api/v1/contracts/{uuid.uuid4()}", json={}, headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db, authenticate_manager):
        owner_mgr = await make_user_model(
            db, username="owner_mgr", email="owner_mgr@example.com", role=UserRole.MANAGER
        )
        prop = await make_property_model(db, manager_id=owner_mgr.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)

        other_mgr_ctx = await authenticate_manager(username="other_mgr", email="other_mgr@example.com")

        response = await client.patch(
            f"/api/v1/contracts/{contract.id}", json={"rent_amount": 2000.0}, headers=other_mgr_ctx.headers
        )
        assert response.status_code == 403

    async def test_returns_409_when_reactivating_onto_property_with_active_contract(
        self,
        client,
        db,
        authenticate_admin,
    ):
        auth_ctx = await authenticate_admin()

        prop = await make_property_model(db)

        tenant1 = await make_tenant_model(db, email="t1-reactivate@example.com")
        tenant2 = await make_tenant_model(db, email="t2-reactivate@example.com")

        terminated_contract = await make_contract_model(db, prop.id, tenant1.id, status="TERMINATED")

        await make_contract_model(db, prop.id, tenant2.id, status="ACTIVE")

        response = await client.patch(
            f"/api/v1/contracts/{terminated_contract.id}",
            json={"status": "ACTIVE"},
            headers=auth_ctx.headers,
        )

        assert response.status_code == 409


@pytest.mark.asyncio
class TestDeleteContractRoute:
    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.delete(f"/api/v1/contracts/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_property(self, client, db, authenticate_manager):
        owner_mgr = await make_user_model(
            db, username="owner_mgr2", email="owner_mgr2@example.com", role=UserRole.MANAGER
        )
        prop = await make_property_model(db, manager_id=owner_mgr.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)

        other_mgr_ctx = await authenticate_manager(username="other_mgr2", email="other_mgr2@example.com")

        response = await client.delete(f"/api/v1/contracts/{contract.id}", headers=other_mgr_ctx.headers)
        assert response.status_code == 403

    async def test_returns_409_when_contract_has_payment(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        await make_payment_model(db, contract.id)

        response = await client.delete(f"/api/v1/contracts/{contract.id}", headers=auth_ctx.headers)
        assert response.status_code == 409

    async def test_returns_409_when_contract_has_document(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        await make_document_model(db, contract_id=contract.id)

        response = await client.delete(f"/api/v1/contracts/{contract.id}", headers=auth_ctx.headers)
        assert response.status_code == 409
