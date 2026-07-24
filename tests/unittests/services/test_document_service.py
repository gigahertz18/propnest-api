import pytest

from io import BytesIO
from types import SimpleNamespace
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from app.services.document_service import DocumentService
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    DocumentForbiddenError,
    DocumentStorageInconsistentError,
    DocumentUploadError,
    ResourceForbiddenError,
)
from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate
from tests.mock_repos import MockCRUDRepo, MockReadOnlyRepo
from tests.factories import make_admin, make_manager


class FailingStorage:
    def put_object(self, bucket, name, stream, length=None, content_type=None):
        raise RuntimeError("Network Error")

    def remove_object(self, bucket, name):
        raise RuntimeError("Network error")


class FakeStorageClient:
    def __init__(self, raise_on_put: Exception | None = None):
        self.put_calls: list[str] = []
        self.remove_calls: list[str] = []
        self.raise_on_put = raise_on_put
        self.objects: dict[str, bytes] = {}

    def put_object(self, bucket, name, stream, length, content_type=None):
        if self.raise_on_put:
            raise self.raise_on_put
        self.put_calls.append(name)
        self.objects[name] = stream.read()

    def remove_object(self, bucket, name):
        self.remove_calls.append(name)
        self.objects.pop(name, None)


class MockDocumentRepoWithScoping(MockCRUDRepo):
    """Adds get_all_for_manager for control-flow testing only — driven by
    a simple manager_id set directly on each mock record, not the real
    property/contract join. The real join semantics are covered by
    DocumentRepository's own tests against a real DB; this only needs to
    confirm DocumentService.list_documents calls the right repo method
    for the right role."""

    async def get_all_for_manager(self, db, manager_id, skip=0, limit=100):
        return [doc for doc in self.records.values() if getattr(doc, "manager_id", None) == manager_id]


def _make_service(properties=None, contracts=None, tenants=None, documents=None):
    return DocumentService(
        document_repo=MockCRUDRepo(documents),
        property_repo=MockReadOnlyRepo(properties),
        contract_repo=MockReadOnlyRepo(contracts),
        tenant_repo=MockReadOnlyRepo(tenants),
    )


@pytest.mark.asyncio
class TestListDocuments:
    async def test_current_user_is_required(self, mock_db):
        """current_user has no default — a caller that forgets to pass it
        gets a loud TypeError, not a silent bypass. This is the specific
        fix for the regression where Tenant/Document authorization was
        silently skippable when current_user was omitted."""
        doc = SimpleNamespace(id=uuid4())
        svc = DocumentService(document_repo=MockDocumentRepoWithScoping({doc.id: doc}))

        with pytest.raises(TypeError):
            await svc.list_documents(mock_db)

    async def test_admin_sees_all_documents(self, mock_db):
        owned = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = DocumentService(document_repo=MockDocumentRepoWithScoping({owned.id: owned, other.id: other}))
        admin = make_admin()

        result = await svc.list_documents(mock_db, current_user=admin)

        assert result.items == [owned, other]
        assert result.total == 2

    async def test_manager_only_sees_documents_for_own_properties(self, mock_db):
        manager = make_manager()
        owned = SimpleNamespace(id=uuid4(), manager_id=manager.id)
        other = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        svc = DocumentService(document_repo=MockDocumentRepoWithScoping({owned.id: owned, other.id: other}))

        result = await svc.list_documents(mock_db, current_user=manager)

        assert result.items == [owned]
        assert result.total == 1


class TestDocumentServiceClassAttributes:
    def test_forbidden_error_is_document_forbidden_error(self):
        """Regression check for the class-attribute refactor: this must
        stay ContractForbiddenError, not the shared ResourceForbiddenError
        base, or routes catching ContractForbiddenError specifically would
        stop matching."""
        assert DocumentService.forbidden_error is DocumentForbiddenError

    def test_document_forbidden_error_is_a_resource_forbidden_error(self):
        assert issubclass(DocumentForbiddenError, ResourceForbiddenError)

    def test_property_repo_and_tenant_repo_default_to_none(self):
        """Only contract_repo is required; property_repo/tenant_repo are
        optional at construction, matching DocumentService's contract."""
        svc = DocumentService(document_repo=document_repo)
        assert svc.property_repo is None
        assert svc.tenant_repo is None
        assert svc.contract_repo is None


@pytest.mark.asyncio
class TestCreateDocument:

    def _payload(self, **kwargs):
        defaults = dict(
            file_name="test.pdf",
            file_type="application/pdf",
            file_url="documents/test.pdf",
            property_id=None,
            contract_id=None,
            tenant_id=None,
        )
        defaults.update(kwargs)
        return DocumentCreate(**defaults)

    async def test_creates_document_without_a_property(self, mock_db):
        """Unattached document (no property/contract/tenant) is valid —
        validation passes, no FK involved, creation succeeds."""
        svc = _make_service()
        result = await svc.create_document(
            mock_db,
            self._payload(),
            current_user=make_admin(),
        )
        assert result.file_name == "test.pdf"
        assert result.property_id is None

    async def test_creates_document_linked_only_to_a_contract(self, mock_db):
        """Contract-only document: contract must exist, manager must own its
        property. Using admin here to isolate the existence-check path."""
        contract_id = uuid4()
        prop_id = uuid4()
        svc = _make_service(
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
        )
        result = await svc.create_document(
            mock_db,
            self._payload(contract_id=contract_id),
            current_user=make_admin(),
        )
        assert result.contract_id == contract_id

    async def test_creates_document_linked_only_to_a_tenant(self, mock_db):
        """Tenant-only document, created by an admin.

        Decision (Option A): _authorize_user_to_property applies uniformly —
        a manager is forbidden on any document with no resolvable property,
        regardless of whether a tenant_id is present. Tenants carry no
        manager-ownership of their own, so there's nothing for a manager
        check to authorize against; "no property in play" is treated the
        same way here as a fully unattached document. See
        test_manager_forbidden_for_tenant_only_document below for the
        manager-denied case this implies.
        """
        tenant_id = uuid4()
        svc = _make_service(tenants={tenant_id: SimpleNamespace(id=tenant_id)})
        result = await svc.create_document(
            mock_db,
            self._payload(tenant_id=tenant_id),
            current_user=make_admin(),
        )
        assert result.tenant_id == tenant_id

    async def test_manager_forbidden_for_tenant_only_document(self, mock_db):
        """Direct consequence of the Option A decision above — a manager
        cannot create a tenant-only document, since there's no property to
        authorize against. Only admins can. Mirrors
        test_manager_forbidden_on_fully_unlinked_document's reasoning."""
        tenant_id = uuid4()
        svc = _make_service(tenants={tenant_id: SimpleNamespace(id=tenant_id)})
        repo = svc.document_repo
        with pytest.raises(DocumentForbiddenError):
            await svc.create_document(
                mock_db,
                self._payload(tenant_id=tenant_id),
                current_user=make_manager(),
            )
        assert repo.created_payloads == []

    async def test_raises_when_property_id_does_not_exist(self, mock_db):
        """Nonexistent property_id → RelatedResourceNotFoundError before
        any DB write. Routes map this to 404."""
        svc = _make_service()
        repo = svc.document_repo
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_document(
                mock_db,
                self._payload(property_id=uuid4()),
                current_user=make_admin(),
            )
        assert repo.created_payloads == []

    async def test_raises_when_contract_id_does_not_exist(self, mock_db):
        """Nonexistent contract_id → RelatedResourceNotFoundError before
        any DB write. Routes map this to 404."""
        svc = _make_service()
        repo = svc.document_repo
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_document(
                mock_db,
                self._payload(contract_id=uuid4()),
                current_user=make_admin(),
            )
        assert repo.created_payloads == []

    async def test_raises_when_tenant_id_does_not_exist(self, mock_db):
        """Nonexistent tenant_id → RelatedResourceNotFoundError before
        any DB write. Routes map this to 404."""
        svc = _make_service()
        repo = svc.document_repo
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.create_document(
                mock_db,
                self._payload(tenant_id=uuid4()),
                current_user=make_admin(),
            )
        assert repo.created_payloads == []

    async def test_manager_can_create_for_owned_property(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)})
        result = await svc.create_document(
            mock_db,
            self._payload(property_id=prop_id),
            current_user=make_manager(manager_id),
        )
        assert result.property_id == prop_id

    async def test_manager_forbidden_for_unowned_property(self, mock_db):
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})
        repo = svc.document_repo
        with pytest.raises(DocumentForbiddenError):
            await svc.create_document(
                mock_db,
                self._payload(property_id=prop_id),
                current_user=make_manager(),  # different manager
            )
        assert repo.created_payloads == []

    async def test_manager_can_create_via_owned_contract(self, mock_db):
        """Manager creates a contract-only document; the contract's property
        is owned by that manager — allowed."""
        manager_id = uuid4()
        prop_id = uuid4()
        contract_id = uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
        )
        result = await svc.create_document(
            mock_db,
            self._payload(contract_id=contract_id),
            current_user=make_manager(manager_id),
        )
        assert result.contract_id == contract_id

    async def test_manager_forbidden_via_unowned_contract(self, mock_db):
        """Manager creates a contract-only document; the contract's property
        belongs to a different manager — forbidden."""
        prop_id = uuid4()
        contract_id = uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
        )
        repo = svc.document_repo
        with pytest.raises(DocumentForbiddenError):
            await svc.create_document(
                mock_db,
                self._payload(contract_id=contract_id),
                current_user=make_manager(),  # outsider
            )
        assert repo.created_payloads == []

    async def test_admin_can_create_for_any_property(self, mock_db):
        """Admin bypasses manager-ownership check entirely."""
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})
        result = await svc.create_document(
            mock_db,
            self._payload(property_id=prop_id),
            current_user=make_admin(),
        )
        assert result.property_id == prop_id


@pytest.mark.asyncio
class TestUpdateDocumentAuthorization:

    def _make_doc(self, **kwargs):
        doc_id = uuid4()
        return doc_id, SimpleNamespace(
            id=doc_id,
            property_id=kwargs.get("property_id"),
            contract_id=kwargs.get("contract_id"),
            tenant_id=kwargs.get("tenant_id"),
        )

    async def test_manager_can_update_when_authorized_via_property(self, mock_db):

        manager_id = uuid4()
        prop_id = uuid4()
        new_prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        svc = _make_service(
            properties={
                prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id),
                new_prop_id: SimpleNamespace(id=new_prop_id, manager_id=manager_id),
            },
            documents={doc_id: doc},
        )
        result = await svc.update_document(
            mock_db,
            doc_id,
            DocumentRelinkUpdate(property_id=new_prop_id),
            current_user=make_manager(manager_id),
        )
        assert result is not None

    async def test_manager_forbidden_when_not_authorized_via_property(self, mock_db):

        prop_id = uuid4()
        new_prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        svc = _make_service(
            properties={
                prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4()),
                new_prop_id: SimpleNamespace(id=new_prop_id, manager_id=uuid4()),
            },
            documents={doc_id: doc},
        )

        with pytest.raises(DocumentForbiddenError):
            await svc.update_document(
                mock_db,
                doc_id,
                DocumentRelinkUpdate(property_id=new_prop_id),
                current_user=make_manager(),
            )

    async def test_manager_can_update_when_authorized_via_contract(self, mock_db):

        manager_id = uuid4()
        prop_id = uuid4()
        contract_id = uuid4()
        new_contract_id = uuid4()
        doc_id, doc = self._make_doc(contract_id=contract_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            contracts={
                contract_id: SimpleNamespace(id=contract_id, property_id=prop_id),
                new_contract_id: SimpleNamespace(id=new_contract_id, property_id=prop_id),
            },
            documents={doc_id: doc},
        )
        result = await svc.update_document(
            mock_db,
            doc_id,
            DocumentRelinkUpdate(contract_id=new_contract_id),
            current_user=make_manager(manager_id),
        )
        assert result is not None

    async def test_manager_forbidden_when_not_authorized_via_contract(self, mock_db):

        prop_id = uuid4()
        contract_id = uuid4()
        new_contract_id = uuid4()
        doc_id, doc = self._make_doc(contract_id=contract_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={
                contract_id: SimpleNamespace(id=contract_id, property_id=prop_id),
                new_contract_id: SimpleNamespace(id=new_contract_id, property_id=prop_id),
            },
            documents={doc_id: doc},
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.update_document(
                mock_db,
                doc_id,
                DocumentRelinkUpdate(contract_id=new_contract_id),
                current_user=make_manager(),
            )

    async def test_manager_cannot_reassign_to_unauthorized_property(self, mock_db):
        """Manager owns the document's *current* property but the payload
        tries to reassign it to a property owned by someone else.
        update_document must re-check auth against the NEW value too."""

        manager_id = uuid4()
        prop_a_id = uuid4()
        prop_b_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_a_id)
        svc = _make_service(
            properties={
                prop_a_id: SimpleNamespace(id=prop_a_id, manager_id=manager_id),
                prop_b_id: SimpleNamespace(id=prop_b_id, manager_id=uuid4()),
            },
            documents={doc_id: doc},
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.update_document(
                mock_db,
                doc_id,
                DocumentRelinkUpdate(property_id=prop_b_id),
                current_user=make_manager(manager_id),
            )

    async def test_raises_when_reassigned_to_nonexistent_property(self, mock_db):
        """Payload contains a property_id that doesn't exist — must raise
        RelatedResourceNotFoundError, not produce a dangling-FK DB error."""

        doc_id, doc = self._make_doc()
        svc = _make_service(documents={doc_id: doc})
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.update_document(
                mock_db,
                doc_id,
                DocumentRelinkUpdate(property_id=uuid4()),
                current_user=make_admin(),
            )

    async def test_manager_forbidden_on_fully_unlinked_document(self, mock_db):
        """No property, no contract → manager cannot update.
        Only admins may touch unattached documents."""

        doc_id, doc = self._make_doc()  # no property_id, no contract_id
        prop_id = uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())}, documents={doc_id: doc}
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.update_document(
                mock_db,
                doc_id,
                DocumentRelinkUpdate(property_id=prop_id),
                current_user=make_manager(),
            )


@pytest.mark.asyncio
class TestDeleteDocumentAuthorization:

    def _make_doc(self, **kwargs):
        doc_id = uuid4()
        return doc_id, SimpleNamespace(
            id=doc_id,
            file_name="test.pdf",
            file_type="application/pdf",
            file_url="documents/test.pdf",
            property_id=kwargs.get("property_id"),
            contract_id=kwargs.get("contract_id"),
            tenant_id=kwargs.get("tenant_id"),
        )

    async def test_manager_can_delete_when_authorized_via_property(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            documents={doc_id: doc},
        )
        result = await svc.delete_document(mock_db, doc_id, current_user=make_manager(manager_id))
        assert result is not None

    async def test_manager_forbidden_when_not_authorized_via_property(self, mock_db):
        prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            documents={doc_id: doc},
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.delete_document(mock_db, doc_id, current_user=make_manager())

    async def test_manager_forbidden_when_not_authorized_via_contract(self, mock_db):
        prop_id = uuid4()
        contract_id = uuid4()
        doc_id, doc = self._make_doc(contract_id=contract_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            documents={doc_id: doc},
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.delete_document(mock_db, doc_id, current_user=make_manager())

    async def test_manager_can_delete_when_authorized_via_contract(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        contract_id = uuid4()
        doc_id, doc = self._make_doc(contract_id=contract_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            contracts={contract_id: SimpleNamespace(id=contract_id, property_id=prop_id)},
            documents={doc_id: doc},
        )
        result = await svc.delete_document(mock_db, doc_id, current_user=make_manager(manager_id))
        assert result is not None

    async def test_manager_forbidden_on_fully_unlinked_document(self, mock_db):
        """No property, no contract → manager cannot delete.
        Only admins may touch unattached documents."""
        doc_id, doc = self._make_doc()
        svc = _make_service(documents={doc_id: doc})
        with pytest.raises(DocumentForbiddenError):
            await svc.delete_document(mock_db, doc_id, current_user=make_manager())


@pytest.mark.asyncio
class TestReplaceDocumentFile:
    def _make_doc(self, file_name="original.pdf", **kwargs):
        doc_id = uuid4()
        return doc_id, DocumentFileUpdate(
            file_name=file_name,
            file_type="application/pdf",
            file_url=f"http://minio/bucket/{file_name}",
            property_id=kwargs.get("property_id"),
            contract_id=kwargs.get("contract_id"),
            tenant_id=kwargs.get("tenant_id"),
        )

    def _make_file_obj(self, filename="replacement.pdf"):
        return SimpleNamespace(content_type="application/pdf", file=BytesIO(b"%PDF-1.4 fake content"))

    async def test_replaces_file_and_returns_updated_document(self, mock_db):
        doc_id, doc = self._make_doc("original.pdf")
        svc = _make_service(documents={doc_id: doc})
        storage = FakeStorageClient()
        _, payload = self._make_doc("replacement.pdf")
        result = await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("replacement.pdf"),
            current_user=make_admin(),
        )

        assert result.file_name == "replacement.pdf"
        # assert "replacement.pdf" in storage.put_calls
        assert svc._build_storage_key(doc_id, "replacement.pdf") in storage.put_calls

    async def test_deletes_old_storage_object_when_filename_changes(self, mock_db):
        """Old object must be removed from MinIO when the new filename
        differs — otherwise orphaned objects accumulate indefinitely."""
        doc_id, doc = self._make_doc("original.pdf")
        storage = FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        _, payload = self._make_doc("replacement.pdf")
        await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("replacement.pdf"),
            current_user=make_admin(),
        )

        # assert "original.pdf" in storage.remove_calls
        assert svc._build_storage_key(doc_id, "original.pdf") in storage.remove_calls

    async def test_does_not_delete_old_object_when_filename_is_the_same(self, mock_db):
        """Same filename → replace-in-place via put_object. Calling
        remove_object on it afterwards would delete the file just uploaded."""
        doc_id, doc = self._make_doc("same_name.pdf")
        storage = FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        _, payload = self._make_doc("same_name.pdf")
        await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("same_name.pdf"),
            current_user=make_admin(),
        )

        # assert "same_name.pdf" not in storage.remove_calls
        assert svc._build_storage_key(doc_id, "same_name.pdf") not in storage.remove_calls

    async def test_manager_authorized_via_existing_property_can_replace(self, mock_db):
        """No relink requested — authorization falls back to the
        document's existing property, mirroring update_document."""
        manager_id = uuid4()
        prop_id = uuid4()
        doc_id, payload = self._make_doc(property_id=prop_id)
        storage = FakeStorageClient()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)},
            documents={doc_id: payload},
        )

        result = await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("new.pdf"),
            current_user=make_manager(manager_id),
        )

        assert result is not None

    async def test_replaces_file_and_relinks_to_new_property_in_one_call(self, mock_db):
        """The core reason this method exists: file replace + relink as a
        single atomic operation, not two separate HTTP round-trips."""
        manager_id = uuid4()
        old_prop_id = uuid4()
        new_prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=old_prop_id)
        _, new_doc = self._make_doc(file_name="new.pdf", property_id=new_prop_id)
        storage = FakeStorageClient()
        svc = _make_service(
            properties={
                old_prop_id: SimpleNamespace(id=old_prop_id, manager_id=manager_id),
                new_prop_id: SimpleNamespace(id=new_prop_id, manager_id=manager_id),
            },
            documents={doc_id: doc},
        )

        result = await svc.replace_document_file(
            mock_db,
            doc_id,
            new_doc,
            storage_client=storage,
            file_obj=self._make_file_obj("new.pdf"),
            current_user=make_manager(manager_id),
        )

        assert result.file_name == "new.pdf"
        assert result.property_id == new_prop_id

    async def test_authorizes_against_new_property_not_old_one(self, mock_db):
        """Anti-bypass check, mirroring update_document's reassignment fix:
        a manager who owns the document's CURRENT property must NOT be able
        to use this call to relink it to a property they don't own."""
        old_manager_id = uuid4()
        old_prop_id = uuid4()
        new_prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=old_prop_id)
        _, payload = self._make_doc(file_name="new.pdf", property_id=new_prop_id)
        storage = FakeStorageClient()
        svc = _make_service(
            properties={
                old_prop_id: SimpleNamespace(id=old_prop_id, manager_id=old_manager_id),
                new_prop_id: SimpleNamespace(id=new_prop_id, manager_id=uuid4()),  # different owner
            },
            documents={doc_id: doc},
        )

        with pytest.raises(DocumentForbiddenError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj("new.pdf"),
                current_user=make_manager(old_manager_id),  # owns OLD property only
            )

        assert storage.put_calls == []

    async def test_raises_when_relink_target_does_not_exist(self, mock_db):
        """A relink property_id that doesn't exist must be caught before
        any storage call — mirrors create_document's existence checks."""
        doc_id, doc = self._make_doc()
        storage = FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        _, payload = self._make_doc(file_name="new.pdf", property_id=uuid4())
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj("new.pdf"),
                current_user=make_admin(),
            )

        assert storage.put_calls == []

    async def test_raise_not_found_on_nonexistent_document(self, mock_db):
        storage = FakeStorageClient()
        svc = _make_service()
        _, payload = self._make_doc(file_name="new.pdf")

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.replace_document_file(
                mock_db,
                uuid4(),
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj(),
                current_user=make_admin(),
            )

    async def test_manager_forbidden_when_not_authorized_via_existing_property(self, mock_db):
        prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        _, payload = self._make_doc(file_name="new.pdf")
        storage = FakeStorageClient()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            documents={doc_id: doc},
        )

        with pytest.raises(DocumentForbiddenError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj(),
                current_user=make_manager(),
            )

        assert storage.put_calls == []

    async def test_manager_forbidden_on_fully_unlinked_document(self, mock_db):
        doc_id, doc = self._make_doc()  # no property, no contract
        storage = FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        payload = DocumentFileUpdate(
            file_name="new.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/new.pdf",
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj(),
                current_user=make_manager(),
            )

        assert storage.put_calls == []

    async def test_storage_failure_raises_and_db_is_not_touched(self, mock_db):
        doc_id, doc = self._make_doc("original.pdf")
        storage = FakeStorageClient(raise_on_put=Exception("MinIO down"))
        svc = _make_service(documents={doc_id: doc})
        repo = svc.document_repo
        payload = DocumentFileUpdate(
            file_name="new.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/new.pdf",
        )

        with pytest.raises(DocumentUploadError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj(),
                current_user=make_admin(),
            )

        assert repo.updated_payloads == []

    async def test_new_storage_object_cleaned_up_when_db_update_fails(self, mock_db):
        """Upload succeeds (to a staging key), DB update raises → the
        staged object must be removed from storage, and neither the OLD
        nor the NEW canonical key is ever touched — promotion never
        happens because the DB record was never actually changed."""
        doc_id, doc = self._make_doc("original.pdf")
        storage = FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        payload = DocumentFileUpdate(
            file_name="new.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/new.pdf",
        )

        async def failing_update(*args, **kwargs):
            raise RuntimeError("DB connection lost")

        svc.document_repo.update = failing_update

        with pytest.raises(RuntimeError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj("new.pdf"),
                current_user=make_admin(),
            )

        new_key = f"documents/{doc_id}_new.pdf"
        old_key = f"documents/{doc_id}_original.pdf"
        assert new_key not in storage.put_calls
        assert new_key not in storage.remove_calls
        assert old_key not in storage.remove_calls
        staged_removals = [k for k in storage.remove_calls if k.startswith(f"documents/_staging/{doc_id}_")]
        assert len(staged_removals) == 1

    async def test_original_file_survives_failed_db_update_with_unchanged_filename(self, mock_db):
        """The exact regression this fix targets: replacing a document's
        file while KEEPING its filename means the 'new' and 'old'
        canonical keys are the literal same string. If the DB update then
        fails, the original bytes at that key must still be there
        afterward — the service must never write to it before the commit
        succeeds."""
        doc_id, doc = self._make_doc("same_name.pdf")
        storage = FakeStorageClient()
        canonical_key = f"documents/{doc_id}_same_name.pdf"
        storage.objects[canonical_key] = b"%PDF-1.4 original content"

        svc = _make_service(documents={doc_id: doc})
        payload = DocumentFileUpdate(
            file_name="same_name.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/same_name.pdf",
        )

        async def failing_update(*args, **kwargs):
            raise RuntimeError("DB connection lost")

        svc.document_repo.update = failing_update

        with pytest.raises(RuntimeError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj("same_name.pdf"),
                current_user=make_admin(),
            )

        # The original object at the canonical key was never touched.
        assert storage.objects[canonical_key] == b"%PDF-1.4 original content"
        assert canonical_key not in storage.remove_calls
        assert canonical_key not in storage.put_calls

    async def test_promotion_failure_after_commit_raises_storage_inconsistent_error(self, mock_db):
        """DB commit succeeds, but writing the staged bytes to the
        canonical key afterward fails (e.g. a transient storage blip) →
        this must surface as DocumentStorageInconsistentError, distinct
        from DocumentUploadError (nothing was persisted) and
        DocumentDeletionError (an orphan couldn't be cleaned up)."""
        doc_id, doc = self._make_doc("original.pdf")
        svc = _make_service(documents={doc_id: doc})
        payload = DocumentFileUpdate(
            file_name="new.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/new.pdf",
        )

        class FailsOnSecondPut(FakeStorageClient):
            def __init__(self):
                super().__init__()
                self._puts = 0

            def put_object(self, bucket, name, stream, length, content_type=None):
                self._puts += 1
                if self._puts >= 2:
                    raise RuntimeError("MinIO blip")
                super().put_object(bucket, name, stream, length, content_type)

        with pytest.raises(DocumentStorageInconsistentError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=FailsOnSecondPut(),
                file_obj=self._make_file_obj("new.pdf"),
                current_user=make_admin(),
            )

    async def test_reraises_original_db_error_when_cleanup_also_fails(self, mock_db):
        doc_id, doc = self._make_doc("original.pdf")
        svc = _make_service(documents={doc_id: doc})
        payload = DocumentFileUpdate(
            file_name="new.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/new.pdf",
        )

        async def failing_update(*args, **kwargs):
            raise IntegrityError("UPDATE", {}, Exception("constraint violation"))

        svc.document_repo.update = failing_update

        class FailingRemoveStorage(FakeStorageClient):
            def remove_object(self, bucket, name):
                raise Exception("MinIO unreachable")

        with pytest.raises(IntegrityError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=FailingRemoveStorage(),
                file_obj=self._make_file_obj("new.pdf"),
                current_user=make_admin(),
            )

    async def test_returns_updated_document_when_old_file_cleanup_fails(self, mock_db):
        """Upload and DB commit both succeed — the DB is already consistent
        at that point, so a failure to delete the now-orphaned old file must
        not turn a successful update into an error for the caller."""
        doc_id, doc = self._make_doc("original.pdf")
        svc = _make_service(documents={doc_id: doc})
        payload = DocumentFileUpdate(
            file_name="new.pdf",
            file_type="application/pdf",
            file_url="http://minio/bucket/new.pdf",
        )

        class FailingRemoveStorage(FakeStorageClient):
            def remove_object(self, bucket, name):
                raise Exception("MinIO unreachable")

        result = await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=FailingRemoveStorage(),
            file_obj=self._make_file_obj("new.pdf"),
            current_user=make_admin(),
        )

        assert result.file_name == "new.pdf"


@pytest.mark.asyncio
class TestCreateDocumentStorageCleanupOnDbFailure:

    async def test_deletes_orphaned_storage_object_when_db_write_fails(self, mock_db, monkeypatch):
        fixed_id = uuid4()
        monkeypatch.setattr("app.services.document_service.uuid4", lambda: fixed_id)

        class FailingCreateRepo(MockCRUDRepo):
            async def create(self, db, payload):
                raise RuntimeError("db write failed")

        deleted_calls = []

        class TrackingStorage:
            def put_object(self, bucket, name, stream, length=None, content_type=None):
                pass

            def remove_object(self, bucket, name):
                deleted_calls.append(name)

        svc = DocumentService(document_repo=FailingCreateRepo())
        payload = DocumentCreate(
            file_name="test.pdf",
            file_type="application/pdf",
            file_url="documents/test.pdf",
            property_id=None,
            contract_id=None,
            tenant_id=None,
        )

        with pytest.raises(RuntimeError):
            await svc.create_document(
                mock_db,
                payload,
                storage_client=TrackingStorage(),
                file_obj=BytesIO(b"%PDF-1.4 content"),
            )

        # assert deleted_calls == ["test.pdf"]
        assert deleted_calls == [svc._build_storage_key(fixed_id, "test.pdf")]

    async def test_skips_cleanup_when_no_file_was_uploaded(self, mock_db):
        """Metadata-only creation (no storage_client/file_obj) has no
        orphaned file to clean up — the guard on line 134 must skip
        _delete_from_storage entirely rather than call it with nothing
        to delete."""

        class FailingCreateRepo(MockCRUDRepo):
            async def create(self, db, payload):
                raise RuntimeError("db write failed")

        svc = DocumentService(document_repo=FailingCreateRepo())
        payload = DocumentCreate(
            file_name="test.pdf",
            file_type="application/pdf",
            file_url="documents/test.pdf",
            property_id=None,
            contract_id=None,
            tenant_id=None,
        )

        with pytest.raises(RuntimeError):
            await svc.create_document(mock_db, payload)  # no storage_client, no file_obj

    async def test_reraises_original_db_error_when_cleanup_also_fails(self, mock_db):
        class FailingCreateRepo(MockCRUDRepo):
            async def create(self, db, payload):
                raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        class FailingStorage:
            def put_object(self, bucket, name, stream, length=None, content_type=None):
                pass

            def remove_object(self, bucket, name):
                raise Exception("MinIO unreachable")

        svc = DocumentService(document_repo=FailingCreateRepo())

        payload = DocumentCreate(
            file_name="test.pdf",
            file_type="application/pdf",
            file_url="documents/test.pdf",
            property_id=None,
            contract_id=None,
            tenant_id=None,
        )

        with pytest.raises(IntegrityError):
            await svc.create_document(
                mock_db,
                payload,
                storage_client=FailingStorage(),
                file_obj=BytesIO(b"%PDF-1.4 content"),
            )


@pytest.mark.asyncio
class TestCreateDocumentStorageKeyIsolation:
    async def test_same_filename_creates_distinct_storage_keys(self, mock_db):
        storage = FakeStorageClient()
        svc = _make_service()

        payload = DocumentCreate(
            file_name="lease.pdf",
            file_type="application/pdf",
            file_url="ignored-by-upload-path",
            property_id=None,
            contract_id=None,
            tenant_id=None,
        )

        first = await svc.create_document(
            mock_db,
            payload,
            storage_client=storage,
            file_obj=BytesIO(b"%PDF-1.4 first"),
            current_user=make_admin(),
        )

        second = await svc.create_document(
            mock_db,
            payload,
            storage_client=storage,
            file_obj=BytesIO(b"%PDF-1.4 second"),
            current_user=make_admin(),
        )

        assert first.file_name == "lease.pdf"
        assert second.file_name == "lease.pdf"
        assert first.id != second.id
        assert storage.put_calls[0] != storage.put_calls[1]
        assert storage.put_calls[0] == svc._build_storage_key(first.id, "lease.pdf")
        assert storage.put_calls[1] == svc._build_storage_key(second.id, "lease.pdf")


@pytest.mark.asyncio
class TestDeleteDocumentRollback:
    """Covers delete_document's generic except branch (lines 277-279):
    any failure that isn't already a DocumentDeletionError still rolls
    back the savepoint before propagating."""

    async def test_rolls_back_savepoint_on_unexpected_error(self, mock_db):
        doc_id = uuid4()
        doc = SimpleNamespace(id=doc_id, file_name="test.pdf", property_id=None, contract_id=None, tenant_id=None)

        class FailingDeleteRepo(MockCRUDRepo):
            async def delete(self, db, id):
                raise RuntimeError("unexpected repo failure")

        svc = DocumentService(document_repo=FailingDeleteRepo({doc_id: doc}))

        with pytest.raises(RuntimeError):
            await svc.delete_document(mock_db, doc_id, current_user=make_admin())

        mock_db.begin_nested.return_value.rollback.assert_called_once()
