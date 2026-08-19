import pytest

from datetime import date, timedelta
from decimal import Decimal

from app.models.property import PropertyStatus
from tests.factories import (
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_lease_model,
    make_billing_record_model,
    make_payment_model,
)


@pytest.mark.asyncio
class TestGetDashboardSummaryRoute:
    async def test_response_contains_all_seven_figures(self, client, authenticate_admin):
        ctx = await authenticate_admin()

        response = await client.get("/api/v1/dashboard/", headers=ctx.headers)

        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {
            "collected_this_month",
            "outstanding",
            "total_credits",
            "late_payments",
            "vacant_units",
            "expiring_leases",
            "recent_payments",
        }

    async def test_aggregates_figures_across_entities(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        lease = await make_lease_model(
            db, contract_id=contract.id, end_date=date.today() + timedelta(days=10), grace_period_days=0
        )
        billing_record = await make_billing_record_model(
            db,
            lease_id=lease.id,
            period_start=date.today().replace(day=1),
            due_date=date.today() - timedelta(days=5),
            amount_due=1000.00,
            status="pending",
        )
        overpaid_record = await make_billing_record_model(
            db,
            lease_id=lease.id,
            period_start=date.today().replace(day=1) + timedelta(days=30),
            amount_due=1000.00,
            status="paid",
        )
        overpaid_record.overpaid_amount = Decimal("150.00")
        db.add(overpaid_record)
        await db.flush()
        await make_payment_model(db, contract.id, amount=500.00)

        response = await client.get("/api/v1/dashboard/", headers=ctx.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["collected_this_month"] == "500.00"
        assert data["outstanding"] == "1000.00"
        assert data["total_credits"] == "150.00"
        assert [r["id"] for r in data["late_payments"]] == [str(billing_record.id)]
        assert [item["id"] for item in data["expiring_leases"]] == [str(lease.id)]
        assert len(data["recent_payments"]) == 1

    async def test_manager_only_sees_own_properties_figures(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        other_mgr = await authenticate_manager(username="other_mgr_dash", email="other_mgr_dash@example.com")
        tenant = await make_tenant_model(db)

        owned_property = await make_property_model(db, manager_id=mgr_ctx.user.id, status=PropertyStatus.vacant)
        other_property = await make_property_model(db, manager_id=other_mgr.user.id, status=PropertyStatus.vacant)

        owned_contract = await make_contract_model(db, owned_property.id, tenant.id)
        other_contract = await make_contract_model(db, other_property.id, tenant.id)

        await make_payment_model(db, owned_contract.id, amount=100.00)
        await make_payment_model(db, other_contract.id, amount=9000.00)

        response = await client.get("/api/v1/dashboard/", headers=mgr_ctx.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["collected_this_month"] == "100.00"
        assert data["vacant_units"] == 1

    async def test_expiring_leases_lookahead_is_configurable(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        lease = await make_lease_model(db, contract_id=contract.id, end_date=date.today() + timedelta(days=20))

        short_window = await client.get("/api/v1/dashboard/?expiring_leases_lookahead_days=5", headers=ctx.headers)
        long_window = await client.get("/api/v1/dashboard/?expiring_leases_lookahead_days=30", headers=ctx.headers)

        assert short_window.json()["expiring_leases"] == []
        assert [item["id"] for item in long_window.json()["expiring_leases"]] == [str(lease.id)]

    async def test_recent_payments_limit_is_configurable(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        for _ in range(3):
            await make_payment_model(db, contract.id)

        response = await client.get("/api/v1/dashboard/?recent_payments_limit=2", headers=ctx.headers)

        assert len(response.json()["recent_payments"]) == 2

    async def test_returns_403_for_plain_user(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get("/api/v1/dashboard/", headers=ctx.headers)
        assert response.status_code == 403
