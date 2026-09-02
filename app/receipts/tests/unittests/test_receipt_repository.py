import pytest
import pytest_asyncio

from app.receipts.repositories.receipt import receipt_repo
from tests.factories import (
    make_contract_model,
    make_document_model,
    make_payment_model,
    make_property_model,
    make_receipt_model,
    make_tenant_model,
)


@pytest_asyncio.fixture
async def property_(db):
    return await make_property_model(db)


@pytest_asyncio.fixture
async def tenant(db):
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def contract(db, property_, tenant):
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


@pytest_asyncio.fixture
async def payment(db, contract):
    return await make_payment_model(db, contract.id)


async def _make_document(db):
    return await make_document_model(db)


@pytest.mark.asyncio
class TestCreate:
    async def test_receipt_number_is_populated_from_server_side_identity(self, db, payment):
        document = await _make_document(db)
        receipt = await receipt_repo.create(db, {"payment_id": payment.id, "document_id": document.id})
        assert isinstance(receipt.receipt_number, int)
        assert receipt.receipt_number > 0


@pytest.mark.asyncio
class TestNextReceiptNumber:
    async def test_strictly_increasing_across_repeated_calls(self, db):
        first = await receipt_repo.next_receipt_number(db)
        second = await receipt_repo.next_receipt_number(db)
        assert second == first + 1


@pytest.mark.asyncio
class TestGetByPayment:
    async def test_returns_multiple_rows_for_the_same_payment(self, db, payment):
        doc_1 = await _make_document(db)
        doc_2 = await _make_document(db)
        receipt_1 = await make_receipt_model(db, payment.id, doc_1.id)
        receipt_2 = await make_receipt_model(db, payment.id, doc_2.id)

        results = await receipt_repo.get_by_payment(db, payment.id)

        assert [r.id for r in results] == [receipt_1.id, receipt_2.id]

    async def test_returns_empty_for_a_payment_with_no_receipts(self, db, payment):
        results = await receipt_repo.get_by_payment(db, payment.id)
        assert results == []
