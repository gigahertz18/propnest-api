"""Shared resource lookup and property-ownership authorization helpers."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.property import Property
from app.models.user import User, UserRole
from app.repositories.contract import ContractRepository
from app.repositories.document import DocumentRepository
from app.repositories.property import PropertyRepository
from app.repositories.tenant import TenantRepository
from app.schemas.base import PaginatedResponse
from app.services.exceptions import RelatedResourceNotFoundError, ResourceForbiddenError


class ResourceAuthorizationMixin:
    """Shared helpers for services that need resource lookup + manager checks."""

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

    @staticmethod
    def _not_found(entity: str, entity_id: UUID) -> RelatedResourceNotFoundError:
        return RelatedResourceNotFoundError(f"{entity} {entity_id} not found.")

    async def _resolve_property(
        self,
        db: AsyncSession,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
    ) -> Property | None:
        """
        Resolve "the property this operation concerns": `property_id` directly
        if given, else via `contract_id`'s poperty, else `None`. Callers with no via-contract
        path just never pass `contract_id`
        """

        if property_id is not None:
            prop = await self._get_property(db, property_id)
            if prop is None:
                raise self._not_found("Property", property_id)
            return prop

        if contract_id is None:
            return None
        contract = await self._get_contract(db, contract_id)
        if contract is None:
            raise self._not_found("Contract", contract_id)

        prop = await self._get_property(db, contract.property_id)
        if prop is None:
            raise self._not_found("Property", contract.property_id)

        return prop

    async def _validate_related_resources(
        self,
        db: AsyncSession,
        *,
        property_id: UUID | None = None,
        contract_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> None:
        """
        Validate that any provided property_id, contract_id, or
        tenant_id actually exists. Existence-checking only, independent
        of authorization; a caller omits whichever ids don't apply.

        Raises:
            RelatedResourceNotFoundError: for the first provided id
                (property, then contract, then tenant) that doesn't
                resolve to an existing record.
        """

        if property_id is not None:
            prop = await self._get_property(db, property_id)
            if prop is None:
                # raise RelatedResourceNotFoundError(f"Property {property_id} not found.")
                raise self._not_found("Property", property_id)

        if contract_id is not None:
            contract = await self._get_contract(db, contract_id)
            if contract is None:
                # raise RelatedResourceNotFoundError(f"Contract {contract_id} not found.")
                raise self._not_found("Contract", contract_id)

        if tenant_id is not None:
            tenant = await self._get_tenant(db, tenant_id)
            if tenant is None:
                # raise RelatedResourceNotFoundError(f"Tenant {tenant_id} not found.")
                raise self._not_found("Tenant", tenant_id)

    async def _authorize_user_to_property(
        self,
        db: AsyncSession,
        current_user: User,
        *,
        property_id: UUID | None,
        contract_id: UUID | None,
    ) -> None:
        """
        Enforce manager-ownership for an operation resolved to a
        property (directly, or via a contract). No-op for admins.
        Non-manager/non-admin roles never reach here — route-level role
        gating already excludes them. Managers must own the resolved
        property; if nothing resolves, managers are forbidden.

        Raises:
            RelatedResourceNotFoundError: bubbled up from `_resolve_property`.
            self.forbidden_error: when a manager isn't authorized (each
                entity overrides this class attribute with its own type).
        """
        if getattr(current_user, "role", None) != UserRole.MANAGER:
            return

        prop = await self._resolve_property(db, property_id=property_id, contract_id=contract_id)

        if prop is None or prop.manager_id != current_user.id:
            raise self.forbidden_error("User not authorized to manage this resource.")

    async def _list_scoped_by_manager(
        self,
        db: AsyncSession,
        current_user: User,
        repo,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse:
        """Admins see everything; managers see only their own, via
        `repo.get_all_for_manager`/`count_all_for_manager`. Shared by
        the Document/Payment/Property/Tenant list endpoints.

        `current_user` is required, not optional: a call site that
        forgets to pass it fails loudly with a TypeError instead of
        silently listing everything to nobody-in-particular — the
        exact silent-bypass bug this codebase was bitten by once.
        """
        if current_user.role == UserRole.MANAGER:
            items = await repo.get_all_for_manager(db, current_user.id, skip=skip, limit=limit)
            total = await repo.count_all_for_manager(db, current_user.id)
        else:
            items = await repo.get_all(db, skip=skip, limit=limit)
            total = await repo.count_all(db)
        return PaginatedResponse(items=items, total=total)
