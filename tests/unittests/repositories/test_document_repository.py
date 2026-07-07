import pytest
import pytest_asyncio
import uuid

from app.repositories.document import document_repo
from app.schemas.document import DocumentCreate, DocumentRelinkUpdate, DocumentFileUpdate
from tests.factories import (
    make_document,
    make_document_model,
    make_property_model,
    make_tenant_model,
    make_contract_model,
)

# ─── Shared fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def property_(db):
    """A persisted Property for FK references."""
    return await make_property_model(db)


@pytest_asyncio.fixture
async def tenant(db):
    """A persisted Tenant for FK references."""
    return await make_tenant_model(db)


@pytest_asyncio.fixture
async def contract(db, property_, tenant):
    """A persisted Contract for FK references."""
    return await make_contract_model(db, property_id=property_.id, tenant_id=tenant.id)


# ─── get_all ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryGetAll:
    async def test_returns_empty_list_when_no_documents(self, db):
        result = await document_repo.get_all(db)
        assert result == []

    async def test_returns_all_documents(self, db):
        await make_document_model(db, file_name="a.pdf")
        await make_document_model(db, file_name="b.pdf")
        result = await document_repo.get_all(db)
        assert len(result) == 2

    async def test_skip_and_limit(self, db):
        for i in range(5):
            await make_document_model(db, file_name=f"doc_{i}.pdf")
        result = await document_repo.get_all(db, skip=2, limit=2)
        assert len(result) == 2

    async def test_limit_zero_returns_empty_list(self, db):
        await make_document_model(db)
        result = await document_repo.get_all(db, limit=0)
        assert result == []

    async def test_skip_beyond_total_returns_empty_list(self, db):
        await make_document_model(db)
        result = await document_repo.get_all(db, skip=100)
        assert result == []

    async def test_negative_skip_is_clamped_to_zero(self, db):
        await make_document_model(db, file_name="a.pdf")
        await make_document_model(db, file_name="b.pdf")
        result = await document_repo.get_all(db, skip=-5)
        # BaseRepository.get_all clamps skip with max(0, skip) — a negative
        # skip should behave the same as skip=0, not raise or skip nothing extra.
        assert len(result) == 2


# ─── get_by_id ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryGetById:
    async def test_returns_document_when_found(self, db):
        doc = await make_document_model(db)
        result = await document_repo.get_by_id(db, doc.id)
        assert result is not None
        assert result.id == doc.id

    async def test_returns_none_when_not_found(self, db):
        result = await document_repo.get_by_id(db, uuid.uuid4())
        assert result is None


# ─── create ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryCreate:
    async def test_creates_document_successfully(self, db):
        payload = DocumentCreate(**make_document())
        result = await document_repo.create(db, payload)
        assert result.id is not None
        assert result.file_name == "test_document.pdf"
        assert result.file_type == "application/pdf"

    async def test_created_document_is_persisted(self, db):
        payload = DocumentCreate(**make_document(file_name="persisted.pdf"))
        created = await document_repo.create(db, payload)
        fetched = await document_repo.get_by_id(db, created.id)
        assert fetched is not None
        assert fetched.file_name == "persisted.pdf"

    async def test_fk_fields_default_to_none(self, db):
        payload = DocumentCreate(**make_document())
        result = await document_repo.create(db, payload)
        assert result.contract_id is None
        assert result.property_id is None
        assert result.tenant_id is None

    async def test_can_link_to_a_property(self, db, property_):
        payload = DocumentCreate(**make_document(property_id=property_.id))
        result = await document_repo.create(db, payload)
        assert result.property_id == property_.id

    async def test_can_link_to_a_tenant(self, db, tenant):
        payload = DocumentCreate(**make_document(tenant_id=tenant.id))
        result = await document_repo.create(db, payload)
        assert result.tenant_id == tenant.id

    async def test_can_link_to_a_contract(self, db, contract):
        payload = DocumentCreate(**make_document(contract_id=contract.id))
        result = await document_repo.create(db, payload)
        assert result.contract_id == contract.id

    async def test_all_fields_are_stored(self, db, property_):
        payload = DocumentCreate(
            **make_document(
                file_name="full.pdf",
                file_type="application/pdf",
                file_url="http://example.com/full.pdf",
                property_id=property_.id,
            )
        )
        result = await document_repo.create(db, payload)
        assert result.file_name == "full.pdf"
        assert result.file_type == "application/pdf"
        assert result.file_url == "http://example.com/full.pdf"
        assert result.property_id == property_.id


# ─── update ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryUpdate:
    async def test_updates_file_name(self, db):
        doc = await make_document_model(db, file_name="old.pdf")
        result = await document_repo.update(
            db, doc.id, DocumentFileUpdate(file_name="new.pdf", file_type=doc.file_type, file_url=doc.file_url)
        )
        assert result.file_name == "new.pdf"

    async def test_partial_update_does_not_affect_other_fields(self, db):
        doc = await make_document_model(db, file_type="application/pdf")
        result = await document_repo.update(
            db, doc.id, DocumentFileUpdate(file_name="renamed.pdf", file_type=doc.file_type, file_url=doc.file_url)
        )
        assert result.file_type == "application/pdf"

    async def test_update_property_link(self, db, property_):
        doc = await make_document_model(db)
        result = await document_repo.update(db, doc.id, DocumentRelinkUpdate(property_id=property_.id))
        assert result.property_id == property_.id

    async def test_explicit_clear_of_property_link(self, db, property_):
        doc = await make_document_model(db, property_id=property_.id)
        # property_id=None is explicitly set on the payload, so
        # exclude_unset=True still includes it — this should clear the FK,
        # unlike a payload that never touches property_id at all.
        result = await document_repo.update(db, doc.id, DocumentRelinkUpdate(property_id=None))
        assert result.property_id is None

    async def test_explicit_clear_of_tenant_link(self, db, tenant):
        doc = await make_document_model(db, tenant_id=tenant.id)
        result = await document_repo.update(db, doc.id, DocumentRelinkUpdate(tenant_id=None))
        assert result.tenant_id is None

    async def test_explicit_clear_of_contract_link(self, db, contract):
        doc = await make_document_model(db, contract_id=contract.id)
        result = await document_repo.update(db, doc.id, DocumentRelinkUpdate(contract_id=None))
        assert result.contract_id is None

    async def test_omitted_property_id_leaves_existing_link_untouched(self, db, property_):
        doc = await make_document_model(db, property_id=property_.id)
        # property_id is never mentioned in the payload, so exclude_unset=True
        # drops it entirely — this must NOT be treated the same as clearing it.
        result = await document_repo.update(
            db, doc.id, DocumentFileUpdate(file_name="renamed.pdf", file_type=doc.file_type, file_url=doc.file_url)
        )
        assert result.property_id == property_.id

    async def test_returns_none_when_not_found(self, db):
        result = await document_repo.update(db, uuid.uuid4(), DocumentRelinkUpdate(property_id=uuid.uuid4()))
        assert result is None

    async def test_updated_value_is_persisted(self, db):
        doc = await make_document_model(db)
        await document_repo.update(
            db, doc.id, DocumentFileUpdate(file_name="saved.pdf", file_type=doc.file_type, file_url=doc.file_url)
        )
        fetched = await document_repo.get_by_id(db, doc.id)
        assert fetched.file_name == "saved.pdf"


# ─── delete ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryDelete:
    async def test_deletes_document_successfully(self, db):
        doc = await make_document_model(db)
        result = await document_repo.delete(db, doc.id)
        assert result is not None
        assert result.id == doc.id

    async def test_deleted_document_is_gone(self, db):
        doc = await make_document_model(db)
        await document_repo.delete(db, doc.id)
        assert await document_repo.get_by_id(db, doc.id) is None

    async def test_returns_none_when_not_found(self, db):
        result = await document_repo.delete(db, uuid.uuid4())
        assert result is None


# ─── get_by_contract ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryGetByContract:
    async def test_returns_documents_for_contract(self, db, contract):
        doc = await make_document_model(db, contract_id=contract.id)
        result = await document_repo.get_by_contract(db, contract.id)
        assert any(d.id == doc.id for d in result)

    async def test_does_not_return_documents_for_other_contracts(self, db, contract):
        await make_document_model(db, contract_id=contract.id)
        result = await document_repo.get_by_contract(db, uuid.uuid4())
        assert result == []

    async def test_returns_multiple_matches(self, db, contract):
        await make_document_model(db, contract_id=contract.id, file_name="a.pdf")
        await make_document_model(db, contract_id=contract.id, file_name="b.pdf")
        result = await document_repo.get_by_contract(db, contract.id)
        assert len([d for d in result if d.contract_id == contract.id]) == 2

    async def test_returns_empty_list_when_no_match(self, db):
        result = await document_repo.get_by_contract(db, uuid.uuid4())
        assert result == []

    async def test_documents_with_no_contract_do_not_leak_into_results(self, db, contract):
        # A document with contract_id=None must never show up for a real contract_id.
        await make_document_model(db, contract_id=None)
        doc = await make_document_model(db, contract_id=contract.id)
        result = await document_repo.get_by_contract(db, contract.id)
        assert all(d.contract_id == contract.id for d in result)
        assert any(d.id == doc.id for d in result)


# ─── get_by_property ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryGetByProperty:
    async def test_returns_documents_for_property(self, db, property_):
        doc = await make_document_model(db, property_id=property_.id)
        result = await document_repo.get_by_property(db, property_.id)
        assert any(d.id == doc.id for d in result)

    async def test_does_not_return_documents_for_other_properties(self, db, property_):
        await make_document_model(db, property_id=property_.id)
        result = await document_repo.get_by_property(db, uuid.uuid4())
        assert result == []

    async def test_returns_empty_list_when_no_match(self, db):
        result = await document_repo.get_by_property(db, uuid.uuid4())
        assert result == []

    async def test_documents_with_no_property_do_not_leak_into_results(self, db, property_):
        await make_document_model(db, property_id=None)
        doc = await make_document_model(db, property_id=property_.id)
        result = await document_repo.get_by_property(db, property_.id)
        assert all(d.property_id == property_.id for d in result)
        assert any(d.id == doc.id for d in result)


# ─── get_by_tenant ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryGetByTenant:
    async def test_returns_documents_for_tenant(self, db, tenant):
        doc = await make_document_model(db, tenant_id=tenant.id)
        result = await document_repo.get_by_tenant(db, tenant.id)
        assert any(d.id == doc.id for d in result)

    async def test_does_not_return_documents_for_other_tenants(self, db, tenant):
        await make_document_model(db, tenant_id=tenant.id)
        result = await document_repo.get_by_tenant(db, uuid.uuid4())
        assert result == []

    async def test_returns_empty_list_when_no_match(self, db):
        result = await document_repo.get_by_tenant(db, uuid.uuid4())
        assert result == []

    async def test_documents_with_no_tenant_do_not_leak_into_results(self, db, tenant):
        await make_document_model(db, tenant_id=None)
        doc = await make_document_model(db, tenant_id=tenant.id)
        result = await document_repo.get_by_tenant(db, tenant.id)
        assert all(d.tenant_id == tenant.id for d in result)
        assert any(d.id == doc.id for d in result)


# ─── get_by_type ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentRepositoryGetByType:
    async def test_returns_documents_of_matching_type(self, db):
        doc = await make_document_model(db, file_type="application/pdf")
        result = await document_repo.get_by_type(db, "application/pdf")
        assert any(d.id == doc.id for d in result)

    async def test_is_exact_match_only(self, db):
        await make_document_model(db, file_type="application/pdf")
        result = await document_repo.get_by_type(db, "application")
        assert result == []

    async def test_returns_multiple_matches(self, db):
        await make_document_model(db, file_type="image/png", file_name="a.png")
        await make_document_model(db, file_type="image/png", file_name="b.png")
        result = await document_repo.get_by_type(db, "image/png")
        assert len([d for d in result if d.file_type == "image/png"]) == 2

    async def test_returns_empty_list_when_no_match(self, db):
        result = await document_repo.get_by_type(db, "application/octet-stream")
        assert result == []
