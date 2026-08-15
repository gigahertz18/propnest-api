from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.user import User
from app.repositories.collection import CollectionRepository
from app.repositories.contract import ContractRepository
from app.repositories.property import PropertyRepository
from app.schemas.base import PaginatedResponse
from app.schemas.collection import CollectionCreate, CollectionUpdate
from app.services.base import ResourceAuthorizationMixin
from app.services.exceptions import (
    CollectionForbiddenError,
    CollectionValidationError,
    RelatedResourceNotFoundError,
)


@dataclass(frozen=True)
class CollectionContext:
    """Fully prepared context for a collection write operation — the
    property has been resolved, the (optional) contract has been checked
    against it, and authorization has passed."""

    collection: Collection | None
    property_id: UUID
    contract_id: UUID | None


class CollectionService(ResourceAuthorizationMixin):
    """Business logic for `Collection` entities — the grouping layer for Documents."""

    forbidden_error = CollectionForbiddenError

    def __init__(
        self,
        collection_repo: CollectionRepository,
        property_repo: PropertyRepository | None = None,
        contract_repo: ContractRepository | None = None,
    ) -> None:
        self.collection_repo = collection_repo
        self.property_repo = property_repo
        self.contract_repo = contract_repo

    async def list_collections(
        self,
        db: AsyncSession,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[Collection]:
        """Admins see every collection; managers only see collections on
        properties they own."""
        return await self._list_scoped_by_manager(db, current_user, self.collection_repo, skip, limit)

    async def get_collection(
        self,
        db: AsyncSession,
        collection_id: UUID,
        current_user: User,
    ) -> Collection:
        collection = await self.collection_repo.get_by_id(db, collection_id)
        if not collection:
            raise RelatedResourceNotFoundError(f"Collection {collection_id} not found.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=collection.property_id,
            contract_id=None,
        )
        return collection

    async def create_collection(
        self,
        db: AsyncSession,
        payload: CollectionCreate,
        current_user: User,
    ) -> Collection:
        ctx = await self._prepare_collection_context(
            db,
            current_user,
            collection=None,
            property_id=payload.property_id,
            contract_id=payload.contract_id,
        )

        resolved_payload = payload.model_copy(update={"property_id": ctx.property_id, "contract_id": ctx.contract_id})

        collection = await self.collection_repo.create(db, resolved_payload)
        await db.commit()
        return collection

    async def update_collection(
        self,
        db: AsyncSession,
        collection_id: UUID,
        payload: CollectionUpdate,
        current_user: User,
    ) -> Collection:
        collection = await self.get_collection(db, collection_id, current_user=current_user)

        if payload.contract_id is not None:
            await self._prepare_collection_context(
                db,
                current_user,
                collection=collection,
                property_id=collection.property_id,
                contract_id=payload.contract_id,
            )

        collection = await self.collection_repo.update(db, collection_id, payload)
        await db.commit()
        return collection

    async def delete_collection(
        self,
        db: AsyncSession,
        collection_id: UUID,
        current_user: User,
    ) -> Collection | None:
        await self.get_collection(db, collection_id, current_user=current_user)

        deleted = await self.collection_repo.delete(db, collection_id)
        await db.commit()
        return deleted

    async def _prepare_collection_context(
        self,
        db: AsyncSession,
        current_user: User,
        *,
        collection: Collection | None,
        property_id: UUID,
        contract_id: UUID | None,
    ) -> CollectionContext:
        """Resolve, validate, and authorize the property/contract context
        for a collection write.

        Raises:
            RelatedResourceNotFoundError: `property_id`/`contract_id` was
                provided but doesn't exist.
            CollectionValidationError: `contract_id` was provided but
                belongs to a different property than `property_id`.
            CollectionForbiddenError: `current_user` isn't authorized.
        """
        await self._validate_related_resources(db, property_id=property_id, contract_id=contract_id)

        if contract_id is not None:
            contract = await self._get_contract(db, contract_id)
            if contract.property_id != property_id:
                raise CollectionValidationError(f"Contract {contract_id} does not belong to property {property_id}.")

        await self._authorize_user_to_property(
            db,
            current_user,
            property_id=property_id,
            contract_id=None,
        )

        return CollectionContext(
            collection=collection,
            property_id=property_id,
            contract_id=contract_id,
        )
