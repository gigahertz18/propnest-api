import pytest
import uuid

from datetime import date

from app.models.user import UserRole
from tests.factories import (
    make_billing_record_model,
    make_contract_model,
    make_lease_model,
    make_property_model,
    make_tenant_model,
    make_user_model,
)


@pytest.mark.asyncio
class TestGenerateBillingRecordRoute:
    async def test_manager_can_generate_for_own_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        payload = {"lease_id": str(lease.id), "period_start": "2026-08-01"}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)

        assert response.status_code == 201
        body = response.json()
        assert body["lease_id"] == str(lease.id)
        assert body["period_start"] == "2026-08-01"
        assert body["status"] == "pending"

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="bmgr1", email="bmgr1@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        payload = {"lease_id": str(lease.id), "period_start": "2026-08-01"}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_lease_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = {"lease_id": str(uuid.uuid4()), "period_start": "2026-08-01"}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 404

    async def test_returns_409_when_already_generated(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        await make_billing_record_model(db, lease_id=lease.id, period_start=date(2026, 8, 1))

        payload = {"lease_id": str(lease.id), "period_start": "2026-08-01"}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 409

    async def test_regular_user_cannot_generate(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        payload = {"lease_id": str(lease.id), "period_start": "2026-08-01"}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 403


@pytest.mark.asyncio
class TestEvaluateOverdueRoute:
    async def test_admin_can_evaluate_overdue_and_late_fee_is_applied(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(
            db, contract_id=contract.id, grace_period_days=3, late_fee_amount=500.00, late_fee_percent=None
        )
        record = await make_billing_record_model(
            db,
            lease_id=lease.id,
            period_start=date(2026, 8, 1),
            due_date=date(2026, 8, 5),
            status="pending",
        )

        response = await client.post(
            f"/api/v1/billing-records/{record.id}/evaluate-overdue",
            params={"as_of": "2026-08-09"},
            headers=ctx.headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "overdue"
        assert body["late_fee_applied"] is True
        assert body["late_fee_amount_charged"] == "500.00"

    async def test_returns_pending_unchanged_before_grace_period(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id, grace_period_days=5)
        record = await make_billing_record_model(
            db,
            lease_id=lease.id,
            period_start=date(2026, 8, 1),
            due_date=date(2026, 8, 5),
            status="pending",
        )

        response = await client.post(
            f"/api/v1/billing-records/{record.id}/evaluate-overdue",
            params={"as_of": "2026-08-08"},
            headers=ctx.headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.post(f"/api/v1/billing-records/{uuid.uuid4()}/evaluate-overdue", headers=ctx.headers)
        assert response.status_code == 404
