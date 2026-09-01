import pytest
import uuid

from app.core.models.audit_log import AuditAction, AuditLog
from tests.factories import (
    make_property_model,
    make_tenant_model,
    make_contract_model,
    make_document_model,
    make_payment_model,
)


def _audit_row(entity_type, entity_id, action=AuditAction.CREATE):
    """Local helper mirroring test_audit_log_repository.py's `_row` —
    actor_id stays None (nullable FK) since these tests exercise
    entity_type/entity_id resolution, not actor identity."""
    return AuditLog(
        id=uuid.uuid4(),
        actor_id=None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )


@pytest.mark.asyncio
class TestGetPropertyActivityRoute:
    async def test_aggregates_events_across_all_entity_types(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        document = await make_document_model(db, property_id=prop.id)
        payment = await make_payment_model(db, contract.id)

        db.add(_audit_row("Property", prop.id))
        db.add(_audit_row("Contract", contract.id))
        db.add(_audit_row("Document", document.id))
        db.add(_audit_row("Payment", payment.id))
        await db.commit()

        response = await client.get(f"/api/v1/properties/{prop.id}/activity", headers=ctx.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4
        assert {item["entity_type"] for item in data["items"]} == {"Property", "Contract", "Document", "Payment"}

    async def test_excludes_events_from_other_properties(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        other_prop = await make_property_model(db)

        db.add(_audit_row("Property", prop.id))
        db.add(_audit_row("Property", other_prop.id))
        await db.commit()

        response = await client.get(f"/api/v1/properties/{prop.id}/activity", headers=ctx.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["entity_id"] == str(prop.id)

    async def test_pagination(self, client, db, authenticate_admin):
        ctx = await authenticate_admin()
        prop = await make_property_model(db)
        for _ in range(3):
            db.add(_audit_row("Property", prop.id))
        await db.commit()

        response = await client.get(f"/api/v1/properties/{prop.id}/activity?skip=1&limit=1", headers=ctx.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 1

    async def test_manager_can_view_owned_propertys_activity(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        prop = await make_property_model(db, manager_id=ctx.user.id)
        db.add(_audit_row("Property", prop.id))
        await db.commit()

        response = await client.get(f"/api/v1/properties/{prop.id}/activity", headers=ctx.headers)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_returns_403_when_manager_does_not_own_property(self, client, db, authenticate_manager):
        ctx = await authenticate_manager()
        other_manager = await authenticate_manager(username="other_manager", email="other_manager@example.com")
        prop = await make_property_model(db, manager_id=other_manager.user.id)

        response = await client.get(f"/api/v1/properties/{prop.id}/activity", headers=ctx.headers)

        assert response.status_code == 403

    async def test_returns_404_when_property_not_found(self, client, authenticate_admin):
        ctx = await authenticate_admin()

        response = await client.get(f"/api/v1/properties/{uuid.uuid4()}/activity", headers=ctx.headers)

        assert response.status_code == 404
