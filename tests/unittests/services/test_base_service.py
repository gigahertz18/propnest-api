import pytest

from types import SimpleNamespace
from uuid import uuid4

from app.models.user import UserRole
from app.services.base import ResourceAuthorizationMixin
from app.services.exceptions import RelatedResourceNotFoundError, ResourceForbiddenError
from tests.mock_repos import MockReadOnlyRepo


class _CustomForbiddenError(Exception):
    """Distinct from ResourceForbiddenError, purely to prove
    _authorize_user_to_property raises whatever `forbidden_error` is set
    on the instance rather than a hardcoded exception type."""


def _make_mixin(
    *,
    properties=None,
    contracts=None,
    tenants=None,
    documents=None,
    forbidden_error=None,
) -> ResourceAuthorizationMixin:
    """
    Builds a bare ResourceAuthorizationMixin instance with test-double
    repos — no concrete service (DocumentService/ContractService)
    involved. The mixin has no abstract methods, so it's directly
    instantiable; using it this way keeps these tests scoped to the
    mixin's own behavior instead of incidentally re-testing whichever
    service happens to be used to construct it.
    """
    mixin = ResourceAuthorizationMixin()
    mixin.property_repo = MockReadOnlyRepo(properties)
    mixin.contract_repo = MockReadOnlyRepo(contracts)
    mixin.tenant_repo = MockReadOnlyRepo(tenants)
    mixin.document_repo = MockReadOnlyRepo(documents)
    if forbidden_error is not None:
        mixin.forbidden_error = forbidden_error
    return mixin


class TestClassDefaults:
    def test_forbidden_error_defaults_to_resource_forbidden_error(self):
        assert ResourceAuthorizationMixin.forbidden_error is ResourceForbiddenError

    def test_all_repos_default_to_none(self):
        mixin = ResourceAuthorizationMixin()
        assert mixin.property_repo is None
        assert mixin.contract_repo is None
        assert mixin.tenant_repo is None
        assert mixin.document_repo is None


# ─── _get_property / _get_contract / _get_tenant / _get_document ──────────


@pytest.mark.asyncio
class TestGetRelatedRecordPrimitives:
    async def test_get_property_returns_property_when_found(self, mock_db):
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id)
        mixin = _make_mixin(properties={prop_id: prop})
        assert await mixin._get_property(mock_db, prop_id) is prop

    async def test_get_property_returns_none_when_not_found(self, mock_db):
        mixin = _make_mixin()
        assert await mixin._get_property(mock_db, uuid4()) is None

    async def test_get_property_raises_when_repo_not_injected(self, mock_db):
        mixin = ResourceAuthorizationMixin()
        with pytest.raises(RuntimeError):
            await mixin._get_property(mock_db, uuid4())

    async def test_get_contract_returns_contract_when_found(self, mock_db):
        contract_id = uuid4()
        contract = SimpleNamespace(id=contract_id)
        mixin = _make_mixin(contracts={contract_id: contract})
        assert await mixin._get_contract(mock_db, contract_id) is contract

    async def test_get_contract_returns_none_when_not_found(self, mock_db):
        mixin = _make_mixin()
        assert await mixin._get_contract(mock_db, uuid4()) is None

    async def test_get_contract_raises_when_repo_not_injected(self, mock_db):
        mixin = ResourceAuthorizationMixin()
        with pytest.raises(RuntimeError):
            await mixin._get_contract(mock_db, uuid4())

    async def test_get_tenant_returns_tenant_when_found(self, mock_db):
        tenant_id = uuid4()
        tenant = SimpleNamespace(id=tenant_id)
        mixin = _make_mixin(tenants={tenant_id: tenant})
        assert await mixin._get_tenant(mock_db, tenant_id) is tenant

    async def test_get_tenant_returns_none_when_not_found(self, mock_db):
        mixin = _make_mixin()
        assert await mixin._get_tenant(mock_db, uuid4()) is None

    async def test_get_tenant_raises_when_repo_not_injected(self, mock_db):
        mixin = ResourceAuthorizationMixin()
        with pytest.raises(RuntimeError):
            await mixin._get_tenant(mock_db, uuid4())

    async def test_get_document_returns_document_when_found(self, mock_db):
        """Previously untested — _get_document is the fourth primitive
        alongside _get_property/_get_contract/_get_tenant, but no test
        exercised it before this file existed."""
        doc_id = uuid4()
        doc = SimpleNamespace(id=doc_id)
        mixin = _make_mixin(documents={doc_id: doc})
        assert await mixin._get_document(mock_db, doc_id) is doc

    async def test_get_document_returns_none_when_not_found(self, mock_db):
        mixin = _make_mixin()
        assert await mixin._get_document(mock_db, uuid4()) is None

    async def test_get_document_raises_when_repo_not_injected(self, mock_db):
        mixin = ResourceAuthorizationMixin()
        with pytest.raises(RuntimeError):
            await mixin._get_document(mock_db, uuid4())


# ─── _resolve_property ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestResolveProperty:
    async def test_returns_none_when_no_property_or_contract_id(self, mock_db):
        mixin = _make_mixin()
        result = await mixin._resolve_property(mock_db, property_id=None, contract_id=None)
        assert result is None

    async def test_resolves_directly_from_property_id(self, mock_db):
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())
        mixin = _make_mixin(properties={prop_id: prop})

        result = await mixin._resolve_property(mock_db, property_id=prop_id, contract_id=None)

        assert result is prop

    async def test_resolves_via_contract_id(self, mock_db):
        prop_id = uuid4()
        contract_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        mixin = _make_mixin(properties={prop_id: prop}, contracts={contract_id: contract})

        result = await mixin._resolve_property(mock_db, property_id=None, contract_id=contract_id)

        assert result is prop

    async def test_property_id_takes_precedence_over_contract_id(self, mock_db):
        """If a caller (incorrectly) passes both, property_id wins —
        matches the documented resolution order."""
        direct_id, via_contract_id, contract_id = uuid4(), uuid4(), uuid4()
        direct_prop = SimpleNamespace(id=direct_id, manager_id=uuid4())
        contract_prop = SimpleNamespace(id=via_contract_id, manager_id=uuid4())
        contract = SimpleNamespace(id=contract_id, property_id=via_contract_id)
        mixin = _make_mixin(
            properties={direct_id: direct_prop, via_contract_id: contract_prop},
            contracts={contract_id: contract},
        )

        result = await mixin._resolve_property(mock_db, property_id=direct_id, contract_id=contract_id)

        assert result is direct_prop

    async def test_raises_when_property_id_does_not_exist(self, mock_db):
        mixin = _make_mixin()
        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._resolve_property(mock_db, property_id=uuid4(), contract_id=None)

    async def test_raises_when_contract_id_does_not_exist(self, mock_db):
        mixin = _make_mixin()
        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._resolve_property(mock_db, property_id=None, contract_id=uuid4())

    async def test_raises_when_contract_points_to_a_missing_property(self, mock_db):
        """Data-integrity edge case: the contract exists but its
        property_id doesn't resolve to an actual property."""
        contract_id = uuid4()
        contract = SimpleNamespace(id=contract_id, property_id=uuid4())
        mixin = _make_mixin(contracts={contract_id: contract})

        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._resolve_property(mock_db, property_id=None, contract_id=contract_id)

    async def test_raises_runtime_error_when_repos_not_injected(self, mock_db):
        mixin = ResourceAuthorizationMixin()
        with pytest.raises(RuntimeError):
            await mixin._resolve_property(mock_db, property_id=uuid4(), contract_id=None)


# ─── _authorize_user_to_property ────────────────────────────────────────────


@pytest.mark.asyncio
class TestAuthorizeManager:
    async def test_admin_is_always_authorized(self, mock_db):
        """Admins skip resolution entirely — this must not even require
        the repos to be injected, since it returns before touching them."""
        mixin = ResourceAuthorizationMixin()
        admin = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN)

        # Should not raise, regardless of property_id/contract_id.
        await mixin._authorize_user_to_property(mock_db, admin, property_id=uuid4(), contract_id=None)

    async def test_manager_authorized_when_owns_property_directly(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=manager_id)
        mixin = _make_mixin(properties={prop_id: prop})
        manager = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)

        await mixin._authorize_user_to_property(mock_db, manager, property_id=prop_id, contract_id=None)

    async def test_manager_authorized_when_owns_property_via_contract(self, mock_db):
        manager_id = uuid4()
        prop_id = uuid4()
        contract_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=manager_id)
        contract = SimpleNamespace(id=contract_id, property_id=prop_id)
        mixin = _make_mixin(properties={prop_id: prop}, contracts={contract_id: contract})
        manager = SimpleNamespace(id=manager_id, role=UserRole.MANAGER)

        await mixin._authorize_user_to_property(mock_db, manager, property_id=None, contract_id=contract_id)

    async def test_manager_forbidden_when_does_not_own_property(self, mock_db):
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())  # owned by someone else
        mixin = _make_mixin(properties={prop_id: prop})
        outsider = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(ResourceForbiddenError):
            await mixin._authorize_user_to_property(mock_db, outsider, property_id=prop_id, contract_id=None)

    async def test_manager_forbidden_when_no_property_or_contract_at_all(self, mock_db):
        """A manager operating on a fully unattached resource (no
        property_id, no contract_id) is forbidden; only admins may."""
        mixin = _make_mixin()
        manager = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(ResourceForbiddenError):
            await mixin._authorize_user_to_property(mock_db, manager, property_id=None, contract_id=None)

    async def test_not_found_propagates_instead_of_being_swallowed_as_forbidden(self, mock_db):
        """A nonexistent property_id is a 404-shaped problem, not a
        403-shaped one — the two exceptions must stay distinguishable."""
        mixin = _make_mixin()
        manager = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._authorize_user_to_property(mock_db, manager, property_id=uuid4(), contract_id=None)

    async def test_raises_whatever_forbidden_error_the_instance_sets(self, mock_db):
        """The whole point of `forbidden_error` being an overridable
        attribute rather than a hardcoded exception is that callers can
        plug in their own type. Previously this was only ever exercised
        with DocumentForbiddenError via a concrete DocumentService, which
        proved DocumentForbiddenError works but not that the mechanism
        is actually generic. Using an arbitrary exception type here
        proves the mixin doesn't hardcode anything."""
        prop_id = uuid4()
        prop = SimpleNamespace(id=prop_id, manager_id=uuid4())  # owned by someone else
        mixin = _make_mixin(properties={prop_id: prop}, forbidden_error=_CustomForbiddenError)
        outsider = SimpleNamespace(id=uuid4(), role=UserRole.MANAGER)

        with pytest.raises(_CustomForbiddenError):
            await mixin._authorize_user_to_property(mock_db, outsider, property_id=prop_id, contract_id=None)


# ─── _validate_related_resources ────────────────────────────────────────────


@pytest.mark.asyncio
class TestValidateRelatedResources:
    async def test_passes_when_nothing_provided(self, mock_db):
        mixin = _make_mixin()
        await mixin._validate_related_resources(mock_db, property_id=None, contract_id=None, tenant_id=None)

    async def test_passes_when_all_provided_and_exist(self, mock_db):
        prop_id, contract_id, tenant_id = uuid4(), uuid4(), uuid4()
        mixin = _make_mixin(
            properties={prop_id: SimpleNamespace(id=prop_id)},
            contracts={contract_id: SimpleNamespace(id=contract_id)},
            tenants={tenant_id: SimpleNamespace(id=tenant_id)},
        )

        await mixin._validate_related_resources(
            mock_db, property_id=prop_id, contract_id=contract_id, tenant_id=tenant_id
        )

    async def test_raises_when_property_id_does_not_exist(self, mock_db):
        mixin = _make_mixin()
        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._validate_related_resources(mock_db, property_id=uuid4(), contract_id=None, tenant_id=None)

    async def test_raises_when_contract_id_does_not_exist(self, mock_db):
        mixin = _make_mixin()
        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._validate_related_resources(mock_db, property_id=None, contract_id=uuid4(), tenant_id=None)

    async def test_raises_when_tenant_id_does_not_exist(self, mock_db):
        mixin = _make_mixin()
        with pytest.raises(RelatedResourceNotFoundError):
            await mixin._validate_related_resources(mock_db, property_id=None, contract_id=None, tenant_id=uuid4())

    async def test_checks_property_before_contract_before_tenant(self, mock_db):
        """Pins down the documented check order: if multiple provided ids
        are all invalid, the property_id error surfaces first."""
        mixin = _make_mixin()
        with pytest.raises(RelatedResourceNotFoundError, match="Property"):
            await mixin._validate_related_resources(
                mock_db, property_id=uuid4(), contract_id=uuid4(), tenant_id=uuid4()
            )

    async def test_raises_runtime_error_when_repos_not_injected(self, mock_db):
        mixin = ResourceAuthorizationMixin()
        with pytest.raises(RuntimeError):
            await mixin._validate_related_resources(mock_db, property_id=uuid4(), contract_id=None, tenant_id=None)
