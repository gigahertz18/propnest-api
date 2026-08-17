import pytest
import uuid

from app.models.audit_log import AuditAction, AuditLog
from app.repositories.activity_feed import activity_feed_repo
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
class TestGetPropertyEntries:
    async def test_returns_rows_for_the_given_property(self, db):
        prop = await make_property_model(db)
        other_prop = await make_property_model(db)
        db.add(_audit_row("Property", prop.id))
        db.add(_audit_row("Property", other_prop.id))
        await db.flush()

        result = await activity_feed_repo.get_property_entries(db, prop.id)

        assert len(result) == 1
        assert result[0].entity_id == prop.id

    async def test_ignores_non_property_entries(self, db):
        prop = await make_property_model(db)
        db.add(_audit_row("Contract", prop.id))
        await db.flush()

        result = await activity_feed_repo.get_property_entries(db, prop.id)

        assert result == []


@pytest.mark.asyncio
class TestGetContractEntries:
    async def test_returns_rows_for_contracts_belonging_to_the_property(self, db):
        prop = await make_property_model(db)
        other_prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        other_contract = await make_contract_model(db, other_prop.id, tenant.id)
        db.add(_audit_row("Contract", contract.id))
        db.add(_audit_row("Contract", other_contract.id))
        await db.flush()

        result = await activity_feed_repo.get_contract_entries(db, prop.id)

        assert len(result) == 1
        assert result[0].entity_id == contract.id

    async def test_ignores_non_contract_entries(self, db):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        db.add(_audit_row("Payment", contract.id))
        await db.flush()

        result = await activity_feed_repo.get_contract_entries(db, prop.id)

        assert result == []


@pytest.mark.asyncio
class TestGetDocumentEntries:
    async def test_returns_rows_for_documents_directly_on_the_property(self, db):
        prop = await make_property_model(db)
        other_prop = await make_property_model(db)
        doc = await make_document_model(db, property_id=prop.id)
        other_doc = await make_document_model(db, property_id=other_prop.id)
        db.add(_audit_row("Document", doc.id))
        db.add(_audit_row("Document", other_doc.id))
        await db.flush()

        result = await activity_feed_repo.get_document_entries(db, prop.id)

        assert len(result) == 1
        assert result[0].entity_id == doc.id

    async def test_returns_rows_for_documents_linked_via_a_contract(self, db):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        doc = await make_document_model(db, contract_id=contract.id)
        db.add(_audit_row("Document", doc.id))
        await db.flush()

        result = await activity_feed_repo.get_document_entries(db, prop.id)

        assert len(result) == 1
        assert result[0].entity_id == doc.id

    async def test_ignores_non_document_entries(self, db):
        prop = await make_property_model(db)
        doc = await make_document_model(db, property_id=prop.id)
        db.add(_audit_row("Payment", doc.id))
        await db.flush()

        result = await activity_feed_repo.get_document_entries(db, prop.id)

        assert result == []


@pytest.mark.asyncio
class TestGetPaymentEntries:
    async def test_returns_rows_for_payments_via_a_contract_on_the_property(self, db):
        prop = await make_property_model(db)
        other_prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        other_contract = await make_contract_model(db, other_prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)
        other_payment = await make_payment_model(db, other_contract.id)
        db.add(_audit_row("Payment", payment.id))
        db.add(_audit_row("Payment", other_payment.id))
        await db.flush()

        result = await activity_feed_repo.get_payment_entries(db, prop.id)

        assert len(result) == 1
        assert result[0].entity_id == payment.id

    async def test_ignores_non_payment_entries(self, db):
        prop = await make_property_model(db)
        tenant = await make_tenant_model(db)
        contract = await make_contract_model(db, prop.id, tenant.id)
        payment = await make_payment_model(db, contract.id)
        db.add(_audit_row("Document", payment.id))
        await db.flush()

        result = await activity_feed_repo.get_payment_entries(db, prop.id)

        assert result == []
