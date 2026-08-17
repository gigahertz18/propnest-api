import pytest

from types import SimpleNamespace
from uuid import uuid4

from app.models.audit_log import AuditAction, AuditLog
from app.services.document_service import DocumentService
from app.services.exceptions import (
    ReceiptForbiddenError,
    RelatedResourceNotFoundError,
    ResourceForbiddenError,
)
from app.services.receipt_service import ReceiptService
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager, make_regular_user


class MockReceiptRepo(MockCRUDRepo):
    """Adds Receipt's own query methods on top of the generic CRUD base.

    `next_receipt_number` fakes the server-side Identity sequence with a
    simple counter — real race-safety is covered by ReceiptRepository's
    own tests against a real DB; this only needs to confirm ReceiptService
    calls it and uses the returned value correctly.
    """

    def __init__(self, records=None):
        super().__init__(records)
        self._counter = 0

    async def next_receipt_number(self, db):
        self._counter += 1
        return self._counter

    async def get_by_payment(self, db, payment_id):
        return await self._filter_by(payment_id=payment_id)


class FakeStorageClient:
    def __init__(self):
        self.put_calls: list[str] = []
        self.objects: dict[str, bytes] = {}

    def put_object(self, bucket, name, stream, length, content_type=None):
        self.put_calls.append(name)
        self.objects[name] = stream.read()

    def remove_object(self, bucket, name):
        self.objects.pop(name, None)


def _make_document_service(documents=None, tenants=None, properties=None, contracts=None) -> DocumentService:
    return DocumentService(
        document_repo=documents if documents is not None else MockCRUDRepo({}),
        property_repo=properties if properties is not None else MockReadOnlyRepo({}),
        contract_repo=contracts if contracts is not None else MockReadOnlyRepo({}),
        tenant_repo=tenants if tenants is not None else MockReadOnlyRepo({}),
    )


def _make_service(
    receipts=None,
    payments=None,
    contracts=None,
    properties=None,
    tenants=None,
    document_service=None,
) -> ReceiptService:
    receipt_repo = receipts if receipts is not None else MockReceiptRepo({})
    payment_repo = payments if payments is not None else MockReadOnlyRepo({})
    contract_repo = contracts if contracts is not None else MockReadOnlyRepo({})
    property_repo = properties if properties is not None else MockReadOnlyRepo({})
    tenant_repo = tenants if tenants is not None else MockReadOnlyRepo({})

    doc_service = document_service or _make_document_service(
        properties=property_repo, contracts=contract_repo, tenants=tenant_repo
    )

    return ReceiptService(
        receipt_repo=receipt_repo,
        payment_repo=payment_repo,
        document_service=doc_service,
        contract_repo=contract_repo,
        property_repo=property_repo,
        tenant_repo=tenant_repo,
    )


def _scenario(manager_id=None):
    """Builds a fully-linked payment -> contract -> property/tenant fixture set."""
    contract_id, prop_id, tenant_id = uuid4(), uuid4(), uuid4()
    payment = SimpleNamespace(
        id=uuid4(),
        contract_id=contract_id,
        amount=15000,
        paid_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
        payment_method="cash",
        reference_number=None,
    )
    contract = SimpleNamespace(id=contract_id, property_id=prop_id, tenant_id=tenant_id)
    property_ = SimpleNamespace(id=prop_id, name="Sunset Villa", manager_id=manager_id or uuid4())
    tenant = SimpleNamespace(id=tenant_id, full_name="Jane Doe")
    return payment, contract, property_, tenant


class TestReceiptServiceClassAttributes:
    def test_forbidden_error_is_receipt_forbidden_error(self):
        assert ReceiptService.forbidden_error is ReceiptForbiddenError

    def test_receipt_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(ReceiptForbiddenError, ResourceForbiddenError)


@pytest.mark.asyncio
class TestIssueReceipt:
    async def test_admin_can_issue_receipt_for_any_payment(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        admin = make_admin()
        receipt = await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())

        assert receipt.payment_id == payment.id
        assert receipt.receipt_number == 1
        assert receipt.document_id is not None
        assert mock_db.commit.called

    async def test_manager_can_issue_receipt_for_owned_property(self, mock_db):
        manager_id = uuid4()
        payment, contract, property_, tenant = _scenario(manager_id=manager_id)
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        receipt = await svc.issue_receipt(
            mock_db, payment.id, make_manager(manager_id), storage_client=FakeStorageClient()
        )
        assert receipt.payment_id == payment.id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        with pytest.raises(ReceiptForbiddenError):
            await svc.issue_receipt(mock_db, payment.id, make_manager(), storage_client=FakeStorageClient())

        assert not mock_db.commit.called

    async def test_user_role_is_forbidden(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        with pytest.raises(ReceiptForbiddenError):
            await svc.issue_receipt(mock_db, payment.id, make_regular_user(), storage_client=FakeStorageClient())

    async def test_raises_when_payment_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.issue_receipt(mock_db, uuid4(), make_admin(), storage_client=FakeStorageClient())

    async def test_writes_audit_log(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        admin = make_admin()
        receipt = await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())

        receipt_rows = [
            call.args[0]
            for call in mock_db.add.call_args_list
            if isinstance(call.args[0], AuditLog) and call.args[0].entity_type == "Receipt"
        ]
        assert len(receipt_rows) == 1
        assert receipt_rows[0].action == AuditAction.CREATE
        assert receipt_rows[0].entity_id == receipt.id
        assert receipt_rows[0].actor_id == admin.id

    async def test_reprint_creates_a_new_receipt_and_document_without_touching_the_first(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        document_repo = MockCRUDRepo({})
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
            document_service=_make_document_service(
                documents=document_repo,
                contracts=MockReadOnlyRepo({contract.id: contract}),
                properties=MockReadOnlyRepo({property_.id: property_}),
                tenants=MockReadOnlyRepo({tenant.id: tenant}),
            ),
        )

        admin = make_admin()
        first = await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())
        second = await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())

        assert first.id != second.id
        assert first.document_id != second.document_id
        assert second.receipt_number == first.receipt_number + 1
        assert first.payment_id == second.payment_id == payment.id
        # Neither Document row was ever updated — append-only.
        assert document_repo.updated_payloads == []


@pytest.mark.asyncio
class TestListReceiptsForPayment:
    async def test_returns_all_receipts_for_a_payment(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        receipt_repo = MockReceiptRepo({})
        svc = _make_service(
            receipts=receipt_repo,
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        admin = make_admin()
        await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())
        await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())

        results = await svc.list_receipts_for_payment(mock_db, payment.id, admin)
        assert len(results) == 2

    async def test_raises_when_payment_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.list_receipts_for_payment(mock_db, uuid4(), make_admin())

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        with pytest.raises(ReceiptForbiddenError):
            await svc.list_receipts_for_payment(mock_db, payment.id, make_manager())


@pytest.mark.asyncio
class TestGetReceipt:
    async def test_raises_when_not_found(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.get_receipt(mock_db, uuid4(), make_admin())

    async def test_admin_can_fetch_any_receipt(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        admin = make_admin()
        issued = await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())

        fetched = await svc.get_receipt(mock_db, issued.id, admin)
        assert fetched.id == issued.id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        payment, contract, property_, tenant = _scenario()
        svc = _make_service(
            payments=MockReadOnlyRepo({payment.id: payment}),
            contracts=MockReadOnlyRepo({contract.id: contract}),
            properties=MockReadOnlyRepo({property_.id: property_}),
            tenants=MockReadOnlyRepo({tenant.id: tenant}),
        )

        admin = make_admin()
        issued = await svc.issue_receipt(mock_db, payment.id, admin, storage_client=FakeStorageClient())

        with pytest.raises(ReceiptForbiddenError):
            await svc.get_receipt(mock_db, issued.id, make_manager())
