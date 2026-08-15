import pytest
import uuid

from app.models.contract import RentalType
from app.models.user import UserRole
from tests.factories import (
    make_lease_model,
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_user_model,
)


@pytest.mark.asyncio
class TestListLeasesRoute:
    async def test_returns_empty_list(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.get("/api/v1/leases/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_admin_sees_all_leases(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        c1 = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        other_prop = await make_property_model(db, name="Other Property")
        c2 = await make_contract_model(db, property_id=other_prop.id, tenant_id=tenant.id)
        await make_lease_model(db, contract_id=c1.id)
        await make_lease_model(db, contract_id=c2.id)

        response = await client.get("/api/v1/leases/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["total"] == 2

    async def test_manager_sees_only_own_property_leases(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="lmgr1", email="lmgr1@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        own_prop = await make_property_model(db, manager_id=ctx.user.id)
        other_prop = await make_property_model(db, manager_id=other_manager.id)

        own_contract = await make_contract_model(db, property_id=own_prop.id, tenant_id=tenant.id)
        other_contract = await make_contract_model(db, property_id=other_prop.id, tenant_id=tenant.id)

        owned = await make_lease_model(db, contract_id=own_contract.id)
        await make_lease_model(db, contract_id=other_contract.id)

        response = await client.get("/api/v1/leases/", headers=ctx.headers)
        assert response.status_code == 200
        ids = {ls["id"] for ls in response.json()["items"]}
        assert ids == {str(owned.id)}

    async def test_regular_user_cannot_list_leases(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get("/api/v1/leases/", headers=ctx.headers)
        assert response.status_code == 403

    async def test_unauthenticated_cannot_list_leases(self, client):
        response = await client.get("/api/v1/leases/")
        assert response.status_code == 403


@pytest.mark.asyncio
class TestGetLeaseRoute:
    async def test_admin_can_get_any_lease(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        response = await client.get(f"/api/v1/leases/{lease.id}", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(lease.id)

    async def test_manager_cannot_get_lease_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="lmgr2", email="lmgr2@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        response = await client.get(f"/api/v1/leases/{lease.id}", headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/leases/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404


@pytest.mark.asyncio
class TestCreateLeaseRoute:
    async def test_manager_can_create_for_own_long_term_contract(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(
            db, property_id=prop.id, tenant_id=tenant.id, rental_type=RentalType.long_term
        )

        payload = {
            "contract_id": str(contract.id),
            "monthly_rent": "15000.00",
            "due_day": 5,
            "late_fee_amount": "500.00",
            "start_date": "2026-01-01",
        }
        response = await client.post("/api/v1/leases/", json=payload, headers=ctx.headers)
        assert response.status_code == 201
        body = response.json()
        assert body["contract_id"] == str(contract.id)
        assert body["status"] == "ACTIVE"

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="lmgr3", email="lmgr3@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(
            db, property_id=prop.id, tenant_id=tenant.id, rental_type=RentalType.long_term
        )

        payload = {
            "contract_id": str(contract.id),
            "monthly_rent": "15000.00",
            "due_day": 5,
            "late_fee_amount": "500.00",
            "start_date": "2026-01-01",
        }
        response = await client.post("/api/v1/leases/", json=payload, headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_contract_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = {
            "contract_id": str(uuid.uuid4()),
            "monthly_rent": "15000.00",
            "due_day": 5,
            "late_fee_amount": "500.00",
            "start_date": "2026-01-01",
        }
        response = await client.post("/api/v1/leases/", json=payload, headers=ctx.headers)
        assert response.status_code == 404

    async def test_returns_400_for_short_term_contract(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(
            db, property_id=prop.id, tenant_id=tenant.id, rental_type=RentalType.short_term
        )

        payload = {
            "contract_id": str(contract.id),
            "monthly_rent": "15000.00",
            "due_day": 5,
            "late_fee_amount": "500.00",
            "start_date": "2026-01-01",
        }
        response = await client.post("/api/v1/leases/", json=payload, headers=ctx.headers)
        assert response.status_code == 400

    async def test_returns_409_when_contract_already_has_a_lease(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(
            db, property_id=prop.id, tenant_id=tenant.id, rental_type=RentalType.long_term
        )
        await make_lease_model(db, contract_id=contract.id)

        payload = {
            "contract_id": str(contract.id),
            "monthly_rent": "15000.00",
            "due_day": 5,
            "late_fee_amount": "500.00",
            "start_date": "2026-01-01",
        }
        response = await client.post("/api/v1/leases/", json=payload, headers=ctx.headers)
        assert response.status_code == 409


@pytest.mark.asyncio
class TestUpdateLeaseRoute:
    async def test_admin_can_update_monthly_rent(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        response = await client.patch(
            f"/api/v1/leases/{lease.id}", json={"monthly_rent": "18000.00"}, headers=ctx.headers
        )
        assert response.status_code == 200
        assert response.json()["monthly_rent"] == "18000.00"

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.patch(
            f"/api/v1/leases/{uuid.uuid4()}", json={"monthly_rent": "18000.00"}, headers=ctx.headers
        )
        assert response.status_code == 404

    async def test_manager_forbidden_for_unowned_lease(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="lmgr4", email="lmgr4@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        response = await client.patch(
            f"/api/v1/leases/{lease.id}", json={"monthly_rent": "18000.00"}, headers=ctx.headers
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestDeleteLeaseRoute:
    async def test_admin_can_delete(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        response = await client.delete(f"/api/v1/leases/{lease.id}", headers=ctx.headers)
        assert response.status_code == 204

        get_response = await client.get(f"/api/v1/leases/{lease.id}", headers=ctx.headers)
        assert get_response.status_code == 404

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.delete(f"/api/v1/leases/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404
