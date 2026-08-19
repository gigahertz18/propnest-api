import pytest
import uuid

from datetime import date, timedelta

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

        payload = {"lease_id": str(lease.id)}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)

        assert response.status_code == 201
        body = response.json()
        assert body["lease_id"] == str(lease.id)
        assert body["period_start"] == lease.start_date.isoformat()
        assert body["status"] == "pending"

    async def test_manager_forbidden_for_another_managers_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await make_user_model(db, username="bmgr1", email="bmgr1@example.com", role=UserRole.MANAGER)
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=other_manager.id)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        payload = {"lease_id": str(lease.id)}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 403

    async def test_returns_404_when_lease_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        payload = {"lease_id": str(uuid.uuid4())}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 404

    async def test_generating_again_after_a_record_exists_advances_to_the_next_period(
        self, client, db, authenticate_admin
    ):
        """period_start is derived server-side from the lease's existing
        billing history, not supplied by the caller, so a record already
        existing for the first period doesn't conflict — it just means the
        next call generates the second period. (The 409 path is reserved
        for a genuine concurrent race — see the unit tests.)"""
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)
        existing = await make_billing_record_model(
            db,
            lease_id=lease.id,
            period_start=lease.start_date,
            period_end=lease.start_date + timedelta(days=30),
            due_date=lease.start_date + timedelta(days=5),
        )

        payload = {"lease_id": str(lease.id)}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)

        assert response.status_code == 201
        body = response.json()
        assert body["period_start"] == (existing.period_end + timedelta(days=1)).isoformat()

    async def test_regular_user_cannot_generate(self, client, db, authenticate_user):
        ctx = await authenticate_user()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id)

        payload = {"lease_id": str(lease.id)}
        response = await client.post("/api/v1/billing-records/generate", json=payload, headers=ctx.headers)
        assert response.status_code == 403

    async def test_first_period_starts_on_lease_start_date_for_a_mid_month_lease(self, client, db, authenticate_admin):
        """A lease starting mid-month (e.g. the 18th) must never be billed
        for days before it started, or leave those first days unbilled —
        the first generated period starts exactly on lease.start_date."""
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id, start_date=date(2026, 8, 18))

        response = await client.post(
            "/api/v1/billing-records/generate", json={"lease_id": str(lease.id)}, headers=ctx.headers
        )

        assert response.status_code == 201
        body = response.json()
        assert body["period_start"] == "2026-08-18"
        assert body["period_end"] == "2026-09-17"

    async def test_second_call_generates_the_next_contiguous_period(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id, start_date=date(2026, 8, 18))

        first = await client.post(
            "/api/v1/billing-records/generate", json={"lease_id": str(lease.id)}, headers=ctx.headers
        )
        second = await client.post(
            "/api/v1/billing-records/generate", json={"lease_id": str(lease.id)}, headers=ctx.headers
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["period_start"] == "2026-09-18"
        assert second.json()["period_end"] == "2026-10-18"


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
