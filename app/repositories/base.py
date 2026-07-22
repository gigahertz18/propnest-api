from collections.abc import Sequence
from typing import Generic, TypeVar, Type
from sqlalchemy import select, Select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.session import Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchema = TypeVar("CreateSchema")
UpdateSchema = TypeVar("UpdateSchema")


class BaseRepository(Generic[ModelType, CreateSchema, UpdateSchema]):
    """
    Generic repository — provides standard CRUD for any model.
    Inherit this and pass in your model + schemas. Only add
    methods that are specific to the child model.
    """

    def __init__(self, model: Type[ModelType]):
        self.model = model

    def _build_query(
        self,
        *criteria,
        order_by=None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Select:
        statement = select(self.model)

        if criteria:
            statement = statement.where(*criteria)

        if order_by is not None:
            statement = statement.order_by(order_by)
        elif hasattr(self.model, "created_at"):
            statement = statement.order_by(self.model.created_at)

        if offset is not None:
            statement = statement.offset(offset)

        if limit is not None:
            statement = statement.limit(limit)

        return statement

    async def _first(
        self,
        db: AsyncSession,
        *criteria,
        **kwargs,
    ) -> ModelType | None:
        result = await db.execute(self._build_query(*criteria, **kwargs))

        return result.scalars().first()

    async def _all(
        self,
        db: AsyncSession,
        *criteria,
        **kwargs,
    ) -> Sequence[ModelType]:
        result = await db.execute(self._build_query(*criteria, **kwargs))

        return result.scalars().all()

    async def _count(
        self,
        db: AsyncSession,
        *criteria,
    ) -> int:
        statement = select(func.count()).select_from(self.model)

        if criteria:
            statement = statement.where(*criteria)

        result = await db.execute(statement)

        return int(result.scalar_one())

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[ModelType]:
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        return await self._all(
            db,
            offset=skip,
            limit=limit,
        )

    async def get_by_id(self, db: AsyncSession, id: UUID) -> ModelType | None:
        return await self._first(
            db,
            self.model.id == id,
        )

    async def get_many_by_ids(
        self,
        db: AsyncSession,
        ids: Sequence[UUID],
    ) -> Sequence[ModelType]:
        """
        Fetch several rows by id in a single query.

        Used any time a caller needs more than one specific row by id instead of looping over `get_by_id` N times.
        """
        if not ids:
            return []

        return await self._all(db, self.model.id.in_(ids))

    async def create(self, db: AsyncSession, payload: CreateSchema) -> ModelType:
        # Accept either a Pydantic model (with `model_dump`) or a plain dict
        if hasattr(payload, "model_dump"):
            data = payload.model_dump()
        elif isinstance(payload, dict):
            data = payload
        else:
            # Fallback: try to coerce to dict
            try:
                data = dict(payload)
            except Exception:
                raise TypeError("Unsupported payload type for create")

        obj = self.model(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def update(
        self,
        db: AsyncSession,
        id: UUID,
        payload: UpdateSchema,
    ) -> ModelType | None:
        obj = await self.get_by_id(db, id)
        if not obj:
            return None
        # Support Pydantic models and plain dicts for updates
        if hasattr(payload, "model_dump"):
            updates = payload.model_dump(exclude_unset=True)
        elif isinstance(payload, dict):
            updates = payload
        else:
            try:
                updates = dict(payload)
            except Exception:
                raise TypeError("Unsupported payload type for update")

        for field, value in updates.items():
            setattr(obj, field, value)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def delete(self, db: AsyncSession, id: UUID) -> ModelType | None:
        obj = await self.get_by_id(db, id)
        if not obj:
            return None
        await db.delete(obj)
        return obj
