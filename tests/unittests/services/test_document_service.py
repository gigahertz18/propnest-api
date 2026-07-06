import pytest

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from app.services.document_service import DocumentService
from app.services.exceptions import (
    RelatedResourceNotFoundError,
    DocumentForbiddenError,
    DocumentUploadError,
)
from app.repositories.document import document_repo
from app.models.user import UserRole
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate


class FailingStorage:
    def put_object(self, bucket, name, stream, length=None, content_type=None):
        raise RuntimeError("Network Error")

    def remove_object(self, bucket, name):
        raise RuntimeError("Network error")


class FakePropertyRepo:
    def __init__(self, properties: dict | None = None):
        self.properties = properties or {}

    async def get_by_id(self, db, id):
        return self.properties.get(id)


class FakeContractRepo:
    def __init__(self, contracts: dict | None = None):
        self.contracts = contracts or {}

    async def get_by_id(self, db, id):
        return self.contracts.get(id)


class FakeTenantRepo:
    def __init__(self, tenants: dict | None = None):
        self.tenants = tenants or {}

    async def get_by_id(self, db, id):
        return self.tenants.get(id)


class FakeDocumentRepo:
    """Stands in for the real document_repo in service unit tests.
    Tracks every operation so tests can assert not only on the outcome
    but also on whether the repo was called at all — the key signal that
    validation/authorization ran *before* any DB write was attempted."""

    def __init__(self, documents: dict | None = None):
        self.documents = documents or {}
        self.created_payloads: list = []
        self.updated_payloads: list = []
        self.deleted_ids: list = []

    async def create(self, db, payload):
        self.created_payloads.append(payload)
        doc = SimpleNamespace(
            id=uuid4(),
            file_name=payload.file_name,
            file_type=payload.file_type,
            file_url=payload.file_url,
            contract_id=payload.contract_id,
            property_id=payload.property_id,
            tenant_id=payload.tenant_id,
        )
        self.documents[doc.id] = doc
        return doc

    async def get_by_id(self, db, id):
        return self.documents.get(id)

    async def update(self, db, id, payload):
        if id not in self.documents:
            return None
        self.updated_payloads.append((id, payload))
        doc = self.documents[id]

        if isinstance(payload, DocumentFileUpdate):
            doc.file_name = payload.file_name
            doc.file_type = payload.file_type
            doc.file_url = payload.file_url

        doc.property_id = payload.property_id
        doc.contract_id = payload.contract_id
        doc.tenant_id = payload.tenant_id
        return doc

    async def delete(self, db, id):
        if id not in self.documents:
            return None
        self.deleted_ids.append(id)
        return self.documents.pop(id)


def _make_service(properties=None, contracts=None, tenants=None, documents=None):
    return DocumentService(
        document_repo=FakeDocumentRepo(documents),
        property_repo=FakePropertyRepo(properties),
        contract_repo=FakeContractRepo(contracts),
        tenant_repo=FakeTenantRepo(tenants),
    )


@pytest.mark.asyncio
class TestGetPropertyContractTenantPrimitives:
    async def test_get_property_returns_property_when_found(self, mock_db):
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id)
        svc = _make_service(properties={prop_id: prop})
        assert await svc._get_property(mock_db, prop_id) is prop

    async def test_get_property_returns_none_when_not_found(self, mock_db):
        svc = _make_service()
        assert await svc._get_property(mock_db, uuid4()) is None

    async def test_get_property_raises_when_repo_not_injected(self, mock_db):
        svc = DocumentService(document_repo=document_repo)
        with pytest.raises(RuntimeError):
            await svc._get_property(mock_db, uuid4())

    async def test_get_contract_returns_contract_when_found(self, mock_db):
        contract_id = uuid4()
        contract = SimpleNamespace(id=contract_id)
        svc = _make_service(contracts={contract_id: contract})
        assert await svc._get_contract(mock_db, contract_id) is contract

    async def test_get_contract_returns_none_when_not_found(self, mock_db):
        svc = _make_service()
        assert await svc._get_contract(mock_db, uuid4()) is None

    async def test_get_contract_raises_when_repo_not_injected(self, mock_db):
        svc = DocumentService(document_repo=document_repo)
        with pytest.raises(RuntimeError):
            await svc._get_contract(mock_db, uuid4())

    async def test_get_tenant_returns_tenant_when_found(self, mock_db):
        tenant_id = uuid4()
        tenant = SimpleNamespace(id=tenant_id)
        svc = _make_service(tenants={tenant_id: tenant})
        assert await svc._get_tenant(mock_db, tenant_id) is tenant

    async def test_get_tenant_returns_none_when_not_found(self, mock_db):
        svc = _make_service()
        assert await svc._get_tenant(mock_db, uuid4()) is None

    async def test_get_tenant_raises_when_repo_not_injected(self, mock_db):
        svc = DocumentService(document_repo=document_repo)
        with pytest.raises(RuntimeError):
            await svc._get_tenant(mock_db, uuid4())


@pytest.mark.asyncio
class TestResolveProperty:
    async def test_returns_none_when_no_property_or_contract_id(self, mock_db):
        svc = _make_service()
        result = await svc._resolve_property(mock_db, property_id=None, contract_id=None)
        assert result is None

    async def test_resolves_directly_from_property_id(self, mock_db):
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())
        svc = _make_service(properties={prop_id: prop})

        result = await svc._resolve_property(mock_db, property_id=prop_id, contract_id=None)

        assert result is prop

    async def test_resolves_via_contract_id(self, mock_db):
        prop_id = uuid4()
        contract_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(properties={prop_id: prop}, contracts={contract_id: contract})

        result = await svc._resolve_property(mock_db, property_id=None, contract_id=contract_id)

        assert result is prop

    async def test_property_id_takes_precedence_over_contract_id(self, mock_db):
        """If a caller (incorrectly) passes both, property_id wins —
        matches the documented resolution order."""
        direct_id, via_contract_id, contract_id = uuid4(), uuid4(), uuid4()
        direct_prop = SimpleNamespace(id=direct_id, manager_id=uuid4())
        contract_prop = SimpleNamespace(id=via_contract_id, manager_id=uuid4())
        contract = SimpleNamespace(id=contract_id, property_id=via_contract_id)
        svc = _make_service(
            properties={direct_id: direct_prop, via_contract_id: contract_prop},
            contracts={contract_id: contract},
        )

        result = await svc._resolve_property(mock_db, property_id=direct_id, contract_id=contract_id)

        assert result is direct_prop

    async def test_raises_when_property_id_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc._resolve_property(mock_db, property_id=uuid4(), contract_id=None)

    async def test_raises_when_contract_id_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc._resolve_property(mock_db, property_id=None, contract_id=uuid4())

    async def test_raises_when_contract_points_to_a_missing_property(self, mock_db):
        """Data-integrity edge case: the contract exists but its
        property_id doesn't resolve to an actual property."""
        contract_id = uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=uuid4())
        svc = _make_service(contracts={contract_id: contract})

        with pytest.raises(RelatedResourceNotFoundError):
            await svc._resolve_property(mock_db, property_id=None, contract_id=contract_id)

    async def test_raises_runtime_error_when_repos_not_injected(self, mock_db):
        svc = DocumentService(document_repo=document_repo)
        with pytest.raises(RuntimeError):
            await svc._resolve_property(mock_db, property_id=uuid4(), contract_id=None)


@pytest.mark.asyncio
class TestAuthorizeManager:
    async def test_admin_is_always_authorized(self, mock_db):
        """Admins skip resolution entirely — this must not even require
        the repos to be injected, since it returns before touching them."""
        svc = DocumentService(document_repo=document_repo)
        admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

        # Should not raise, regardless of property_id/contract_id.
        await svc._authorize_user_to_property(mock_db, admin, property_id=uuid4(), contract_id=None)

    async def test_manager_authorized_when_owns_property_directly(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=manager_id)
        svc = _make_service(properties={prop_id: prop})
        manager = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)

        await svc._authorize_user_to_property(mock_db, manager, property_id=prop_id, contract_id=None)

    async def test_manager_authorized_when_owns_property_via_contract(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        contract_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=manager_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        svc = _make_service(properties={prop_id: prop}, contracts={contract_id: contract})
        manager = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)

        await svc._authorize_user_to_property(mock_db, manager, property_id=None, contract_id=contract_id)

    async def test_manager_forbidden_when_does_not_own_property(self, mock_db):
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())  # owned by someone else
        svc = _make_service(properties={prop_id: prop})
        outsider = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(DocumentForbiddenError):
            await svc._authorize_user_to_property(mock_db, outsider, property_id=prop_id, contract_id=None)

    async def test_manager_forbidden_when_no_property_or_contract_at_all(self, mock_db):
        """Deliberate decision, not an accident — see the helper's
        docstring. A manager operating on a fully unattached document
        (no property_id, no contract_id) is forbidden; only admins may.
        This is the rule create_document will inherit once migrated,
        fixing its current asymmetry with update/delete."""
        svc = _make_service()
        manager = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(DocumentForbiddenError):
            await svc._authorize_user_to_property(mock_db, manager, property_id=None, contract_id=None)

    async def test_not_found_propagates_instead_of_being_swallowed_as_forbidden(self, mock_db):
        """A nonexistent property_id is a 404-shaped problem, not a
        403-shaped one — the two exceptions must stay distinguishable."""
        svc = _make_service()
        manager = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(RelatedResourceNotFoundError):
            await svc._authorize_user_to_property(mock_db, manager, property_id=uuid4(), contract_id=None)


@pytest.mark.asyncio
class TestValidateRelatedResources:
    async def test_passes_when_nothing_provided(self, mock_db):
        svc = _make_service()
        await svc._validate_related_resources(
            mock_db,
            property_id=None,
            contract_id=None,
            tenant_id=None,
        )

    async def test_passes_when_all_provided_and_exist(self, mock_db):
        prop_id, contract_id, tenant_id = uuid4(), uuid4(), uuid4()
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id)},
            contracts={contract_id: SimpleNamespace(id=contract_id)},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        await svc._validate_related_resources(
            mock_db, property_id=prop_id, contract_id=contract_id, tenant_id=tenant_id
        )

    async def test_raises_when_property_id_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc._validate_related_resources(
                mock_db,
                property_id=uuid4(),
                contract_id=None,
                tenant_id=None,
            )

    async def test_raises_when_contract_id_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc._validate_related_resources(
                mock_db,
                property_id=None,
                contract_id=uuid4(),
                tenant_id=None,
            )

    async def test_raises_when_tenant_id_does_not_exist(self, mock_db):
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError):
            await svc._validate_related_resources(
                mock_db,
                property_id=None,
                contract_id=None,
                tenant_id=uuid4(),
            )

    async def test_checks_property_before_contract_before_tenant(self, mock_db):
        """Pins down the documented check order: if multiple provided ids
        are all invalid, the property_id error surfaces first."""
        svc = _make_service()
        with pytest.raises(RelatedResourceNotFoundError, match="Property"):
            await svc._validate_related_resources(
                mock_db,
                property_id=uuid4(),
                contract_id=uuid4(),
                tenant_id=uuid4(),
            )

    async def test_raises_runtime_error_when_repos_not_injected(self, mock_db):
        svc = DocumentService(document_repo=document_repo)
        with pytest.raises(RuntimeError):
            await svc._validate_related_resources(
                mock_db,
                property_id=uuid4(),
                contract_id=None,
                tenant_id=None,
            )


@pytest.mark.asyncio
class TestCreateDocument:
    """
    Service-level equivalents of the TODO-marked tests in TestCreateDocumentRoute
    in test_document_api.py. Each test here exercises DocumentService directly —
    no HTTP client, no real DB. The paired API test can shrink to a one-liner
    status-code assertion once these service tests are green.
    """

    def _make_admin(self):
        return SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

    def _make_manager(self, manager_id=None):
        return SimpleNamespace(id=manager_id or uuid4(), role=UserRole.MANAGER)

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
            current_user=self._make_admin(),
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
            current_user=self._make_admin(),
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
            current_user=self._make_admin(),
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
                current_user=self._make_manager(),
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
                current_user=self._make_admin(),
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
                current_user=self._make_admin(),
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
                current_user=self._make_admin(),
            )
        assert repo.created_payloads == []

    async def test_manager_can_create_for_owned_property(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=manager_id)})
        result = await svc.create_document(
            mock_db,
            self._payload(property_id=prop_id),
            current_user=self._make_manager(manager_id),
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
                current_user=self._make_manager(),  # different manager
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
            current_user=self._make_manager(manager_id),
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
                current_user=self._make_manager(),  # outsider
            )
        assert repo.created_payloads == []

    async def test_admin_can_create_for_any_property(self, mock_db):
        """Admin bypasses manager-ownership check entirely."""
        prop_id = uuid4()
        svc = _make_service(properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())})
        result = await svc.create_document(
            mock_db,
            self._payload(property_id=prop_id),
            current_user=self._make_admin(),
        )
        assert result.property_id == prop_id


@pytest.mark.asyncio
class TestUpdateDocumentAuthorization:

    def _make_admin(self):
        return SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

    def _make_manager(self, manager_id=None):
        return SimpleNamespace(id=manager_id or uuid4(), role=UserRole.MANAGER)

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
            current_user=self._make_manager(manager_id),
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
                current_user=self._make_manager(),
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
            current_user=self._make_manager(manager_id),
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
                current_user=self._make_manager(),
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
                current_user=self._make_manager(manager_id),
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
                current_user=self._make_admin(),
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
                current_user=self._make_manager(),
            )


@pytest.mark.asyncio
class TestDeleteDocumentAuthorization:

    def _make_admin(self):
        return SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

    def _make_manager(self, manager_id=None):
        return SimpleNamespace(id=manager_id or uuid4(), role=UserRole.MANAGER)

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
        result = await svc.delete_document(mock_db, doc_id, current_user=self._make_manager(manager_id))
        assert result is not None

    async def test_manager_forbidden_when_not_authorized_via_property(self, mock_db):
        prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        svc = _make_service(
            properties={prop_id: SimpleNamespace(id=prop_id, manager_id=uuid4())},
            documents={doc_id: doc},
        )
        with pytest.raises(DocumentForbiddenError):
            await svc.delete_document(mock_db, doc_id, current_user=self._make_manager())

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
            await svc.delete_document(mock_db, doc_id, current_user=self._make_manager())

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
        result = await svc.delete_document(mock_db, doc_id, current_user=self._make_manager(manager_id))
        assert result is not None

    async def test_manager_forbidden_on_fully_unlinked_document(self, mock_db):
        """No property, no contract → manager cannot delete.
        Only admins may touch unattached documents."""
        doc_id, doc = self._make_doc()
        svc = _make_service(documents={doc_id: doc})
        with pytest.raises(DocumentForbiddenError):
            await svc.delete_document(mock_db, doc_id, current_user=self._make_manager())


@pytest.mark.asyncio
class TestReplaceDocumentFile:
    def _make_admin(self):
        return SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

    def _make_manager(self, manager_id=None):
        return SimpleNamespace(id=manager_id or uuid4(), role=UserRole.MANAGER)

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

    class FakeStorageClient:
        def __init__(self, raise_on_put: Exception | None = None):
            self.put_calls: list[str] = []
            self.remove_calls: list[str] = []
            self.raise_on_put = raise_on_put

        def put_object(self, bucket, name, stream, length, content_type=None):
            if self.raise_on_put:
                raise self.raise_on_put
            self.put_calls.append(name)

        def remove_object(self, bucket, name):
            self.remove_calls.append(name)

    def _make_file_obj(self, filename="replacement.pdf"):
        return SimpleNamespace(content_type="application/pdf", file=BytesIO(b"%PDF-1.4 fake content"))

    async def test_replaces_file_and_returns_updated_document(self, mock_db):
        doc_id, doc = self._make_doc("original.pdf")
        svc = _make_service(documents={doc_id: doc})
        storage = self.FakeStorageClient()
        _, payload = self._make_doc("replacement.pdf")
        result = await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("replacement.pdf"),
            current_user=self._make_admin(),
        )

        assert result.file_name == "replacement.pdf"
        assert "replacement.pdf" in storage.put_calls

    async def test_deletes_old_storage_object_when_filename_changes(self, mock_db):
        """Old object must be removed from MinIO when the new filename
        differs — otherwise orphaned objects accumulate indefinitely."""
        doc_id, doc = self._make_doc("original.pdf")
        storage = self.FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        _, payload = self._make_doc("replacement.pdf")
        await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("replacement.pdf"),
            current_user=self._make_admin(),
        )

        assert "original.pdf" in storage.remove_calls

    async def test_does_not_delete_old_object_when_filename_is_the_same(self, mock_db):
        """Same filename → replace-in-place via put_object. Calling
        remove_object on it afterwards would delete the file just uploaded."""
        doc_id, doc = self._make_doc("same_name.pdf")
        storage = self.FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        _, payload = self._make_doc("same_name.pdf")
        await svc.replace_document_file(
            mock_db,
            doc_id,
            payload,
            storage_client=storage,
            file_obj=self._make_file_obj("same_name.pdf"),
            current_user=self._make_admin(),
        )

        assert "same_name.pdf" not in storage.remove_calls

    async def test_manager_authorized_via_existing_property_can_replace(self, mock_db):
        """No relink requested — authorization falls back to the
        document's existing property, mirroring update_document."""
        manager_id = uuid4()
        prop_id = uuid4()
        doc_id, payload = self._make_doc(property_id=prop_id)
        storage = self.FakeStorageClient()
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
            current_user=self._make_manager(manager_id),
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
        storage = self.FakeStorageClient()
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
            current_user=self._make_manager(manager_id),
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
        storage = self.FakeStorageClient()
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
                current_user=self._make_manager(old_manager_id),  # owns OLD property only
            )

        assert storage.put_calls == []

    async def test_raises_when_relink_target_does_not_exist(self, mock_db):
        """A relink property_id that doesn't exist must be caught before
        any storage call — mirrors create_document's existence checks."""
        doc_id, doc = self._make_doc()
        storage = self.FakeStorageClient()
        svc = _make_service(documents={doc_id: doc})
        _, payload = self._make_doc(file_name="new.pdf", property_id=uuid4())
        with pytest.raises(RelatedResourceNotFoundError):
            await svc.replace_document_file(
                mock_db,
                doc_id,
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj("new.pdf"),
                current_user=self._make_admin(),
            )

        assert storage.put_calls == []

    async def test_raise_not_found_on_nonexistent_document(self, mock_db):
        storage = self.FakeStorageClient()
        svc = _make_service()
        _, payload = self._make_doc(file_name="new.pdf")

        with pytest.raises(RelatedResourceNotFoundError):
            await svc.replace_document_file(
                mock_db,
                uuid4(),
                payload,
                storage_client=storage,
                file_obj=self._make_file_obj(),
                current_user=self._make_admin(),
            )

    async def test_manager_forbidden_when_not_authorized_via_existing_property(self, mock_db):
        prop_id = uuid4()
        doc_id, doc = self._make_doc(property_id=prop_id)
        _, payload = self._make_doc(file_name="new.pdf")
        storage = self.FakeStorageClient()
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
                current_user=self._make_manager(),
            )

        assert storage.put_calls == []

    async def test_manager_forbidden_on_fully_unlinked_document(self, mock_db):
        doc_id, doc = self._make_doc()  # no property, no contract
        storage = self.FakeStorageClient()
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
                current_user=self._make_manager(),
            )

        assert storage.put_calls == []

    async def test_storage_failure_raises_and_db_is_not_touched(self, mock_db):
        doc_id, doc = self._make_doc("original.pdf")
        storage = self.FakeStorageClient(raise_on_put=Exception("MinIO down"))
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
                current_user=self._make_admin(),
            )

        assert repo.updated_payloads == []

    async def test_new_storage_object_cleaned_up_when_db_update_fails(self, mock_db):
        """Upload succeeds, DB update raises → the newly uploaded object
        must be removed from storage, and the OLD object must be left
        alone since the DB record was never actually changed."""
        doc_id, doc = self._make_doc("original.pdf")
        storage = self.FakeStorageClient()
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
                current_user=self._make_admin(),
            )

        assert "new.pdf" in storage.remove_calls
        assert "original.pdf" not in storage.remove_calls
