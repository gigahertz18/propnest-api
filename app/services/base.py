"""
Shared resource-resolution and authorization primitives.

This mixin is for services whose operations act on a Property (directly,
or indirectly via a Contract) and need to enforce manager-ownership
authorization against it. `DocumentService` and `ContractService` both
mix this in.

What this mixin owns:
- fetching a single related record by id (`_get_property`, `_get_contract`,
  `_get_tenant`, `_get_document`)
- validating that a set of optionally-provided ids actually exist
  (`_validate_related_resources`)
- resolving "the property this operation concerns", directly or via a
  contract (`_resolve_property`)
- authorizing a user against that resolved property
  (`_authorize_user_to_property`)

What it deliberately does NOT own (and why):
- Each operation's `Context` dataclass shape — `DocumentContext` and
  `ContractContext` have different fields because the entities do.
- Defaulting logic for "no id was given, fall back to the existing
  record's stored id" — that requires knowing which kind of record you're
  holding, which is entity-specific.
- Which exception type means "forbidden" for a given entity —
  `DocumentForbiddenError` and `ContractForbiddenError` are distinct, so
  `_authorize_user_to_property` takes the exception type as a parameter
  rather than hardcoding one.

Note on scope: this mixin is specifically about *resource-ownership*
authorization (does this manager own the resolved property). It is not a
general-purpose "any authorization check" home — e.g. `UserService`'s
self-or-admin check needs no repo lookup at all and does not belong here.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.property import Property
from app.models.user import User, UserRole
from app.repositories.contract import ContractRepository
from app.repositories.document import DocumentRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.services.exceptions import RelatedResourceNotFoundError, ResourceForbiddenError


class ResourceAuthorizationMixin:
    """Mixed into services that need to resolve/validate/authorize against
    Property, Contract, Tenant, and/or Document records.

    Subclasses set whichever of these repos they need in `__init__`. A repo
    left as `None` raises `RuntimeError` if a method that needs it is
    actually called, rather than silently no-op-ing.
    """

    property_repo: PropertyRepository | None = None
    contract_repo: ContractRepository | None = None
    tenant_repo: TenantRepository | None = None
    document_repo: DocumentRepository | None = None
    forbidden_error: type[Exception] = ResourceForbiddenError

    async def _get_property(self, db: AsyncSession, property_id: UUID) -> Property | None:
        if self.property_repo is None:
            raise RuntimeError(f"{type(self).__name__}._get_property requires property_repo to be injected.")
        return await self.property_repo.get_by_id(db, property_id)

    async def _get_contract(self, db: AsyncSession, contract_id: UUID):
        if self.contract_repo is None:
            raise RuntimeError(f"{type(self).__name__}._get_contract requires contract_repo to be injected.")
        return await self.contract_repo.get_by_id(db, contract_id)

    async def _get_tenant(self, db: AsyncSession, tenant_id: UUID):
        if self.tenant_repo is None:
            raise RuntimeError(f"{type(self).__name__}._get_tenant requires tenant_repo to be injected.")
        return await self.tenant_repo.get_by_id(db, tenant_id)

    async def _get_document(self, db: AsyncSession, document_id: UUID):
        if self.document_repo is None:
            raise RuntimeError(f"{type(self).__name__}._get_document requires document_repo to be injected.")
        return await self.document_repo.get_by_id(db, document_id)

    async def _resolve_property(
        self,
        db: AsyncSession,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
    ) -> Property | None:
        """
        Resolve "the property this operation concerns".

        Resolution order:
        1. `property_id`, if provided -> direct lookup
        2. otherwise, if `contract_id` is provided, look up the contract,
           then look up its property
        3. otherwise `None`

        Callers whose entity has no indirect, via-contract path (e.g.
        `ContractService`) simply never pass `contract_id` — that branch
        stays inert rather than being duplicated per-caller.
        """
        if property_id is not None:
            prop = await self._get_property(db, property_id)
            if prop is None:
                raise RelatedResourceNotFoundError(f"Property {property_id} not found.")
            return prop

        if contract_id is not None:
            contract = await self._get_contract(db, contract_id)
            if contract is None:
                raise RelatedResourceNotFoundError(f"Contract {contract_id} not found.")
            prop = await self._get_property(db, contract.property_id)
            if prop is None:
                raise RelatedResourceNotFoundError(f"Property {contract.property_id} not found.")
            return prop

        return None

    async def _validate_related_resources(
        self,
        db: AsyncSession,
        *,
        property_id: UUID | None = None,
        contract_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> None:
        """
        Validate that any provided property_id, contract_id, or tenant_id
        actually exists. Purely existence-checking, independent of
        authorization and independent of which entity is calling — a
        caller simply omits whichever ids don't apply to it.

        Raises:
            RelatedResourceNotFoundError: for the first of property_id,
                contract_id, or tenant_id (checked in that order) that is
                provided but doesn't resolve to an existing record.
        """
        if property_id is not None:
            prop = await self._get_property(db, property_id)
            if prop is None:
                raise RelatedResourceNotFoundError(f"Property {property_id} not found.")

        if contract_id is not None:
            contract = await self._get_contract(db, contract_id)
            if contract is None:
                raise RelatedResourceNotFoundError(f"Contract {contract_id} not found.")

        if tenant_id is not None:
            tenant = await self._get_tenant(db, tenant_id)
            if tenant is None:
                raise RelatedResourceNotFoundError(f"Tenant {tenant_id} not found.")

    async def _authorize_user_to_property(
        self,
        db: AsyncSession,
        current_user: User,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
    ) -> None:
        """
        Enforce manager-ownership authorization for an operation resolved
        to a property (directly, or via a contract).

        - Admins are always authorized; this is a no-op for them.
        - Non-manager, non-admin roles aren't handled here — route-level
          role gating (e.g. `require_manager_or_above`) already excludes
          them from reaching mutating endpoints at all.
        - Managers must own the resolved property. If nothing resolves,
          managers are forbidden — only admins may operate on unattached
          resources.

        Args:
            forbidden_error: the exception type to raise on denial. Each
                entity has its own (`DocumentForbiddenError`,
                `ContractForbiddenError`, ...), so this is caller-supplied
                rather than hardcoded, letting routes keep mapping each to
                the right HTTP response.

        Raises:
            RelatedResourceNotFoundError: bubbled up from `_resolve_property`
                when a provided property_id/contract_id doesn't exist.
            forbidden_error: when a manager isn't authorized.
        """
        if getattr(current_user, "role", None) != UserRole.MANAGER:
            return

        prop = await self._resolve_property(db, property_id=property_id, contract_id=contract_id)

        if not prop or prop.manager_id != current_user.id:
            raise self.forbidden_error("User not authorized to manage this resource.")
