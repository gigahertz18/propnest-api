from typing import Generic, TypeVar, Type
from sqlalchemy.orm import Session
from app.db.session import Base

from uuid import UUID

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

    def get_all(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ModelType]:
        skip = max(0, skip)
        limit = min(max(0, limit), 100)

        query = db.query(self.model)
        if hasattr(self.model, "created_at"):
            query = query.order_by(self.model.created_at)
        return query.offset(skip).limit(limit).all()

    def get_by_id(self, db: Session, id: UUID) -> ModelType | None:
        return db.query(self.model).filter(self.model.id == id).first()

    def create(self, db: Session, payload: CreateSchema) -> ModelType:
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
        db.commit()
        db.refresh(obj)
        return obj

    def update(
        self,
        db: Session,
        id: UUID,
        payload: UpdateSchema,
    ) -> ModelType | None:
        obj = self.get_by_id(db, id)
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
        db.commit()
        db.refresh(obj)
        return obj

    def delete(self, db: Session, id: UUID) -> ModelType | None:
        obj = self.get_by_id(db, id)
        if not obj:
            return None
        db.delete(obj)
        db.commit()
        return obj
