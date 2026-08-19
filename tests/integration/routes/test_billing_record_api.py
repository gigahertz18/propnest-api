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
class TestListBillingRecordRoute:
    async def test_manager_lists_records_for_owned_lease(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, period_start=date(2026, 8, 1))

        other_prop = await make_property_model(db, name="Other Property", manager_id=ctx.user.id)
        other_contract = await make_contract_model(db, property_id=other_prop.id, tenant_id=tenant.id)
        other_lease = await make_lease_model(db, contract_id=other_contract.id)
        await make_billing_record_model(db, lease_id=other_lease.id, period_start=date(2026, 8, 1))

        response = await client.get("/api/v1/billing-records/", params={"lease_id": str(lease.id)}, headers=ctx.headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(record.id)

    async def test_returns_404_when_lease_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get(
            "/api/v1/billing-records/", params={"lease_id": str(uuid.uuid4())}, headers=ctx.headers
        )
        assert response.status_code == 404

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="bmgr2", email="bmgr2@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        response = await client.get("/api/v1/billing-records/", params={"lease_id": str(lease.id)}, headers=ctx.headers)
        assert response.status_code == 403


@pytest.mark.asyncio
class TestGetBillingRecordRoute:
    async def test_manager_gets_record_for_owned_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, period_start=date(2026, 8, 1))

        response = await client.get(f"/api/v1/billing-records/{record.id}", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(record.id)

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/billing-records/{uuid.uuid4()}", headers=ctx.headers)
        assert response.status_code == 404

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="bmgr3", email="bmgr3@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, period_start=date(2026, 8, 1))

        response = await client.get(f"/api/v1/billing-records/{record.id}", headers=ctx.headers)
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


@pytest.mark.asyncio
class TestWriteOffBillingRecordRoute:
    async def test_admin_can_write_off_overdue_record(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="overdue")

        response = await client.post(f"/api/v1/billing-records/{record.id}/write-off", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json()["status"] == "written_off"

    async def test_returns_409_when_transition_invalid(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="pending")

        response = await client.post(f"/api/v1/billing-records/{record.id}/write-off", headers=ctx.headers)
        assert response.status_code == 409

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.post(f"/api/v1/billing-records/{uuid.uuid4()}/write-off", headers=ctx.headers)
        assert response.status_code == 404

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="bmgr4", email="bmgr4@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="overdue")

        response = await client.post(f"/api/v1/billing-records/{record.id}/write-off", headers=ctx.headers)
        assert response.status_code == 403

    async def test_regular_user_forbidden(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="overdue")

        response = await client.post(f"/api/v1/billing-records/{record.id}/write-off", headers=ctx.headers)
        assert response.status_code == 403


@pytest.mark.asyncio
class TestCorrectLateFeeRoute:
    async def test_admin_can_correct_late_fee_on_overdue_record(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(
            db, lease_id=lease.id, status="overdue", late_fee_applied=True, late_fee_amount_charged=500.00
        )

        payload = {"late_fee_applied": False, "late_fee_amount_charged": None}
        response = await client.patch(
            f"/api/v1/billing-records/{record.id}/late-fee", json=payload, headers=ctx.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["late_fee_applied"] is False
        assert body["late_fee_amount_charged"] is None

    async def test_returns_422_when_amount_missing_but_applied_true(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="overdue")

        payload = {"late_fee_applied": True, "late_fee_amount_charged": None}
        response = await client.patch(
            f"/api/v1/billing-records/{record.id}/late-fee", json=payload, headers=ctx.headers
        )
        assert response.status_code == 422

    async def test_returns_409_when_record_is_paid(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="paid")

        payload = {"late_fee_applied": True, "late_fee_amount_charged": 100.00}
        response = await client.patch(
            f"/api/v1/billing-records/{record.id}/late-fee", json=payload, headers=ctx.headers
        )
        assert response.status_code == 409

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = {"late_fee_applied": False, "late_fee_amount_charged": None}
        response = await client.patch(
            f"/api/v1/billing-records/{uuid.uuid4()}/late-fee", json=payload, headers=ctx.headers
        )
        assert response.status_code == 404

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="bmgr5", email="bmgr5@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        record = await make_billing_record_model(db, lease_id=lease.id, status="overdue")

        payload = {"late_fee_applied": True, "late_fee_amount_charged": 100.00}
        response = await client.patch(
            f"/api/v1/billing-records/{record.id}/late-fee", json=payload, headers=ctx.headers
        )
        assert response.status_code == 403
