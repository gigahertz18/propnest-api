import pytest
import uuid

from tests.factories import (
    make_manager_model,
    make_contract_model,
    make_property_model,
    make_tenant_model,
    make_payment_model,
    make_lease_model,
    make_billing_record_model,
)


@pytest.mark.asyncio
class TestListPaymentRoute:
    async def test_returns_empty_list(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/payments/", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_returns_all_payments_for_admin(self, client, db, authenticate_admin):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        await make_payment_model(db, contract.id, status="PAID")
        await make_payment_model(db, contract.id, status="PENDING")

        auth_ctx = await authenticate_admin()
        response = await client.get("/api/v1/payments/", headers=auth_ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 2
        assert len(resp_data["items"]) == 2

    async def test_manager_only_sees_payments_for_owned_properties(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        other_mgr = await authenticate_manager(username="other_mgr", email="other_mgr@example.com")
        owned_prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        other_prop = await make_property_model(db, name="Other Property", manager_id=other_mgr.user.id)
        tenant = await make_tenant_model(db)

        owned_contract = await make_contract_model(db, owned_prop.id, tenant.id)
        other_contract = await make_contract_model(db, other_prop.id, tenant.id)

        owned_payment = await make_payment_model(db, owned_contract.id)
        await make_payment_model(db, other_contract.id)

        response = await client.get("/api/v1/payments/", headers=mgr_ctx.headers)
        assert response.status_code == 200
        resp_data = response.json()
        assert resp_data["total"] == 1
        assert resp_data["items"][0]["id"] == str(owned_payment.id)


@pytest.mark.asyncio
class TestGetPaymentRoute:
    async def test_returns_payment_by_id(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        response = await client.get(f"/api/v1/payments/{payment.id}", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == str(payment.id)

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/payments/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_returns_403_when_manager_not_authorized_for_contract(self, client, db, authenticate_manager):
        owner_mgr = await make_manager_model(db, username="owner_mgr", email="owner_mgr@example.com")
        prop = await make_property_model(db, manager_id=owner_mgr.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        other_mgr_ctx = await authenticate_manager(username="other_mgr", email="other_mgr@example.com")

        response = await client.get(f"/api/v1/payments/{payment.id}", headers=other_mgr_ctx.headers)
        assert response.status_code == 403


@pytest.mark.asyncio
class TestCreatePaymentRoute:
    async def test_manager_forbidden_for_unmanaged_contract(self, client, db, authenticate_manager):
        mgr1_ctx = await authenticate_manager(username="mgr1", email="mgr1@example.com")
        mgr2 = await make_manager_model(db, username="mgr2", email="mgr2@example.com")
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr2.id)
        contract = await make_contract_model(db, prop.id, tenant.id)

        payload = {
            "contract_id": str(contract.id),
            "amount": 5000.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=mgr1_ctx.headers)
        assert response.status_code == 403

    async def test_manager_can_create_for_owned_contract(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        contract = await make_contract_model(db, prop.id, tenant.id)

        payload = {
            "contract_id": str(contract.id),
            "amount": 5000.0,
            "payment_method": "gcash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=mgr_ctx.headers)
        assert response.status_code == 201
        assert response.json()["contract_id"] == str(contract.id)

    async def test_returns_404_when_contract_does_not_exist(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        payload = {
            "contract_id": str(uuid.uuid4()),
            "amount": 5000.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_422_for_invalid_payment_method(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)

        payload = {
            "contract_id": str(contract.id),
            "amount": 5000.0,
            "payment_method": "bitcoin",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 422

    async def test_returns_422_for_non_positive_amount(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)

        payload = {
            "contract_id": str(contract.id),
            "amount": 0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 422


@pytest.mark.asyncio
class TestCreatePaymentAgainstBillingRecordRoute:
    async def _billing_record(self, db, amount_due=15000.00):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        lease = await make_lease_model(db, contract.id, monthly_rent=amount_due)
        record = await make_billing_record_model(db, lease.id, amount_due=amount_due)
        return contract, record

    async def test_partial_payment_updates_billing_record_to_partially_paid(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        contract, record = await self._billing_record(db)

        payload = {
            "contract_id": str(contract.id),
            "billing_record_id": str(record.id),
            "amount": 5000.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 201
        assert response.json()["billing_record_id"] == str(record.id)

        await db.refresh(record)
        assert record.status == "partially_paid"

    async def test_full_payment_updates_billing_record_to_paid(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        contract, record = await self._billing_record(db)

        payload = {
            "contract_id": str(contract.id),
            "billing_record_id": str(record.id),
            "amount": 15000.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 201

        await db.refresh(record)
        assert record.status == "paid"
        assert record.overpaid_amount is None

    async def test_overpayment_updates_billing_record_to_paid_with_excess_tracked(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        contract, record = await self._billing_record(db)

        payload = {
            "contract_id": str(contract.id),
            "billing_record_id": str(record.id),
            "amount": 15500.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 201

        await db.refresh(record)
        assert record.status == "paid"
        assert float(record.overpaid_amount) == 500.0

    async def test_returns_404_when_billing_record_belongs_to_different_contract(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        _, record = await self._billing_record(db)

        other_prop = await make_property_model(db, name="Other Property")
        other_tenant = await make_tenant_model(db, email="other-tenant@example.com")
        other_contract = await make_contract_model(db, other_prop.id, other_tenant.id)

        payload = {
            "contract_id": str(other_contract.id),
            "billing_record_id": str(record.id),
            "amount": 5000.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_payment_without_billing_record_id_is_unaffected(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)

        payload = {
            "contract_id": str(contract.id),
            "amount": 5000.0,
            "payment_method": "cash",
            "status": "PAID",
        }

        response = await client.post("/api/v1/payments/", json=payload, headers=auth_ctx.headers)
        assert response.status_code == 201
        assert response.json()["billing_record_id"] is None


@pytest.mark.asyncio
class TestUpdatePaymentRoute:
    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.patch(f"/api/v1/payments/{uuid.uuid4()}", json={}, headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_contract(self, client, db, authenticate_manager):
        owner_mgr = await make_manager_model(db, username="owner_mgr2", email="owner_mgr2@example.com")
        prop = await make_property_model(db, manager_id=owner_mgr.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        other_mgr_ctx = await authenticate_manager(username="other_mgr2", email="other_mgr2@example.com")

        response = await client.patch(
            f"/api/v1/payments/{payment.id}", json={"status": "REFUNDED"}, headers=other_mgr_ctx.headers
        )
        assert response.status_code == 403

    async def test_admin_can_update_status(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id, status="PAID")

        response = await client.patch(
            f"/api/v1/payments/{payment.id}", json={"status": "REFUNDED"}, headers=auth_ctx.headers
        )
        assert response.status_code == 200
        assert response.json()["status"] == "REFUNDED"

    async def test_returns_422_when_setting_status_to_voided(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id, status="PAID")

        response = await client.patch(
            f"/api/v1/payments/{payment.id}", json={"status": "VOIDED"}, headers=auth_ctx.headers
        )
        assert response.status_code == 422

    async def test_returns_409_when_updating_a_voided_payment(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id, status="VOIDED")

        response = await client.patch(
            f"/api/v1/payments/{payment.id}", json={"amount": 999.0}, headers=auth_ctx.headers
        )
        assert response.status_code == 409


@pytest.mark.asyncio
class TestCorrectPaymentRoute:
    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        payload = {"amount": 5000.0, "payment_method": "cash"}
        response = await client.post(
            f"/api/v1/payments/{uuid.uuid4()}/corrections", json=payload, headers=auth_ctx.headers
        )
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_contract(self, client, db, authenticate_manager):
        owner_mgr = await make_manager_model(db, username="owner_mgr4", email="owner_mgr4@example.com")
        prop = await make_property_model(db, manager_id=owner_mgr.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        other_mgr_ctx = await authenticate_manager(username="other_mgr4", email="other_mgr4@example.com")

        payload = {"amount": 5000.0, "payment_method": "cash"}
        response = await client.post(
            f"/api/v1/payments/{payment.id}/corrections", json=payload, headers=other_mgr_ctx.headers
        )
        assert response.status_code == 403

    async def test_admin_can_correct_payment(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id, amount=1000.0)

        payload = {"amount": 2500.0, "payment_method": "gcash", "reference_number": "REF-1"}
        response = await client.post(
            f"/api/v1/payments/{payment.id}/corrections", json=payload, headers=auth_ctx.headers
        )
        assert response.status_code == 201
        body = response.json()
        assert body["corrects_payment_id"] == str(payment.id)
        assert body["contract_id"] == str(contract.id)
        assert body["amount"] == "2500.00"
        assert body["reference_number"] == "REF-1"

        original = await client.get(f"/api/v1/payments/{payment.id}", headers=auth_ctx.headers)
        assert original.json()["status"] == "VOIDED"

    async def test_manager_can_correct_owned_payment(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        payload = {"amount": 3000.0, "payment_method": "cash"}
        response = await client.post(
            f"/api/v1/payments/{payment.id}/corrections", json=payload, headers=mgr_ctx.headers
        )
        assert response.status_code == 201

    async def test_returns_409_when_correcting_an_already_voided_payment(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id, status="VOIDED")

        payload = {"amount": 3000.0, "payment_method": "cash"}
        response = await client.post(
            f"/api/v1/payments/{payment.id}/corrections", json=payload, headers=auth_ctx.headers
        )
        assert response.status_code == 409

    async def test_returns_422_for_invalid_payment_method(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        payload = {"amount": 3000.0, "payment_method": "bitcoin"}
        response = await client.post(
            f"/api/v1/payments/{payment.id}/corrections", json=payload, headers=auth_ctx.headers
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestDeletePaymentRoute:
    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.delete(f"/api/v1/payments/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404

    async def test_returns_403_when_manager_not_authorized_for_contract(self, client, db, authenticate_manager):
        owner_mgr = await make_manager_model(db, username="owner_mgr3", email="owner_mgr3@example.com")
        prop = await make_property_model(db, manager_id=owner_mgr.id)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        other_mgr_ctx = await authenticate_manager(username="other_mgr3", email="other_mgr3@example.com")

        response = await client.delete(f"/api/v1/payments/{payment.id}", headers=other_mgr_ctx.headers)
        assert response.status_code == 403

    async def test_admin_can_delete_any_payment(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)

        response = await client.delete(f"/api/v1/payments/{payment.id}", headers=auth_ctx.headers)
        assert response.status_code == 204
        assert response.content == b""
