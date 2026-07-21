from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import Generic, TypeVar


class BaseResponse(BaseModel):
    model_config = {
        "from_attributes": True,
        "json_encoders": {
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S"),
            date: lambda v: v.strftime("%Y-%m-%d"),
        },
    }  # Allows reading from SQLAlchemy model


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
