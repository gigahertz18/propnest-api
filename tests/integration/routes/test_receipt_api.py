import pytest
import uuid

from app.core.dependencies import get_storage_client
from app.main import app
from tests.factories import (
    make_contract_model,
    make_manager_model,
    make_property_model,
    make_tenant_model,
)


class FakeStorageClient:
    """Minimal stand-in for the MinIO client — only what DocumentService touches."""

    def __init__(self, raise_on_put: Exception | None = None):
        self.raise_on_put = raise_on_put
        self.put_calls: list = []

    def put_object(self, *args, **kwargs):
        if self.raise_on_put:
            raise self.raise_on_put
        self.put_calls.append((args, kwargs))

    def remove_object(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _override_storage_client():
    app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient()
    yield
    app.dependency_overrides.pop(get_storage_client, None)


async def _make_payment_via_route(client, headers, contract_id, amount=5000.0):
    payload = {
        "contract_id": str(contract_id),
        "amount": amount,
        "payment_method": "cash",
        "status": "PAID",
    }
    return await client.post("/api/v1/payments/", json=payload, headers=headers)


@pytest.mark.asyncio
class TestAutomaticReceiptIssuanceOnPaymentCreation:
    async def test_recording_a_payment_auto_issues_a_receipt(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        contract = await make_contract_model(db, prop.id, tenant.id)

        response = await _make_payment_via_route(client, mgr_ctx.headers, contract.id)
        assert response.status_code == 201
        payment_id = response.json()["id"]

        receipts_response = await client.get(f"/api/v1/payments/{payment_id}/receipts", headers=mgr_ctx.headers)
        assert receipts_response.status_code == 200
        receipts = receipts_response.json()
        assert len(receipts) == 1
        assert receipts[0]["receipt_number"] >= 1
        assert receipts[0]["payment_id"] == payment_id

    async def test_payment_creation_still_succeeds_when_receipt_issuance_fails(self, client, db, authenticate_manager):
        app.dependency_overrides[get_storage_client] = lambda: FakeStorageClient(raise_on_put=RuntimeError("boom"))
        mgr_ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        contract = await make_contract_model(db, prop.id, tenant.id)

        response = await _make_payment_via_route(client, mgr_ctx.headers, contract.id)
        assert response.status_code == 201

        receipts_response = await client.get(
            f"/api/v1/payments/{response.json()['id']}/receipts", headers=mgr_ctx.headers
        )
        assert receipts_response.json() == []


@pytest.mark.asyncio
class TestIssueReceiptRoute:
    async def test_reprint_creates_a_second_distinct_receipt(self, client, db, authenticate_manager):
        mgr_ctx = await authenticate_manager()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr_ctx.user.id)
        contract = await make_contract_model(db, prop.id, tenant.id)

        create_response = await _make_payment_via_route(client, mgr_ctx.headers, contract.id)
        payment_id = create_response.json()["id"]

        reprint_response = await client.post(f"/api/v1/payments/{payment_id}/receipts", headers=mgr_ctx.headers)
        assert reprint_response.status_code == 201

        receipts_response = await client.get(f"/api/v1/payments/{payment_id}/receipts", headers=mgr_ctx.headers)
        receipts = receipts_response.json()
        assert len(receipts) == 2
        numbers = sorted(r["receipt_number"] for r in receipts)
        assert numbers[1] == numbers[0] + 1
        doc_ids = {r["document_id"] for r in receipts}
        assert len(doc_ids) == 2

    async def test_returns_403_when_manager_not_authorized_for_contract(self, client, db, authenticate_manager):
        mgr1_ctx = await authenticate_manager(username="mgr1", email="mgr1@example.com")
        mgr2 = await make_manager_model(db, username="mgr2", email="mgr2@example.com")
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db, manager_id=mgr2.id)
        contract = await make_contract_model(db, prop.id, tenant.id)

        create_response = await _make_payment_via_route(client, mgr1_ctx.headers, contract.id)
        assert create_response.status_code == 403

    async def test_returns_404_for_unknown_payment(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.post(f"/api/v1/payments/{uuid.uuid4()}/receipts", headers=auth_ctx.headers)
        assert response.status_code == 404


@pytest.mark.asyncio
class TestGetReceiptRoute:
    async def test_get_receipt_by_id(self, client, db, authenticate_admin):
        auth_ctx = await authenticate_admin()
        tenant = await make_tenant_model(db)
        prop = await make_property_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)

        create_response = await _make_payment_via_route(client, auth_ctx.headers, contract.id)
        payment_id = create_response.json()["id"]

        receipts = (await client.get(f"/api/v1/payments/{payment_id}/receipts", headers=auth_ctx.headers)).json()
        receipt_id = receipts[0]["id"]

        response = await client.get(f"/api/v1/receipts/{receipt_id}", headers=auth_ctx.headers)
        assert response.status_code == 200
        assert response.json()["id"] == receipt_id

    async def test_returns_404_when_not_found(self, client, authenticate_admin):
        auth_ctx = await authenticate_admin()
        response = await client.get(f"/api/v1/receipts/{uuid.uuid4()}", headers=auth_ctx.headers)
        assert response.status_code == 404
