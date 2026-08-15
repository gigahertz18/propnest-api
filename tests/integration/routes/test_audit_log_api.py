import pytest

from tests.factories import make_contract_model, make_property_model, make_tenant_model


@pytest.mark.asyncio
class TestListAuditLogsRoute:
    async def test_returns_empty_list(self, client, authenticate_admin):
        ctx = await authenticate_admin()
        response = await client.get("/api/v1/audit-logs/", headers=ctx.headers)
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    async def test_manager_cannot_list_audit_logs(self, client, authenticate_manager):
        ctx = await authenticate_manager()
        response = await client.get("/api/v1/audit-logs/", headers=ctx.headers)
        assert response.status_code == 403

    async def test_regular_user_cannot_list_audit_logs(self, client, authenticate_user):
        ctx = await authenticate_user()
        response = await client.get("/api/v1/audit-logs/", headers=ctx.headers)
        assert response.status_code == 403

    async def test_unauthenticated_cannot_list_audit_logs(self, client):
        response = await client.get("/api/v1/audit-logs/")
        assert response.status_code == 403

    async def test_creating_a_property_produces_exactly_one_audit_row(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()

        payload = {"name": "Unit A", "address": "123 Main St"}
        create_resp = await client.post("/api/v1/properties/", json=payload, headers=ctx.headers)
        assert create_resp.status_code == 201
        prop_id = create_resp.json()["id"]

        response = await client.get(
            "/api/v1/audit-logs/", params={"entity_type": "Property", "entity_id": prop_id}, headers=ctx.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        row = body["items"][0]
        assert row["action"] == "CREATE"
        assert row["entity_type"] == "Property"
        assert row["entity_id"] == prop_id
        assert row["actor_id"] == str(ctx.user.id)

    async def test_creating_a_payment_produces_exactly_one_audit_row(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, property_id=prop.id, tenant_id=tenant.id)

        payload = {"contract_id": str(contract.id), "amount": 5000.0, "payment_method": "cash"}
        create_resp = await client.post("/api/v1/payments/", json=payload, headers=ctx.headers)
        assert create_resp.status_code == 201
        payment_id = create_resp.json()["id"]

        response = await client.get(
            "/api/v1/audit-logs/", params={"entity_type": "Payment", "entity_id": payment_id}, headers=ctx.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["action"] == "CREATE"

    async def test_filters_by_entity_type(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        await client.post("/api/v1/properties/", json={"name": "A", "address": "Addr A"}, headers=ctx.headers)
        await client.post("/api/v1/properties/", json={"name": "B", "address": "Addr B"}, headers=ctx.headers)

        response = await client.get("/api/v1/audit-logs/", params={"entity_type": "Property"}, headers=ctx.headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert all(item["entity_type"] == "Property" for item in body["items"])

    async def test_pagination(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        for i in range(3):
            await client.post(
                "/api/v1/properties/", json={"name": f"Prop {i}", "address": f"Addr {i}"}, headers=ctx.headers
            )

        response = await client.get("/api/v1/audit-logs/", params={"skip": 1, "limit": 1}, headers=ctx.headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 1
