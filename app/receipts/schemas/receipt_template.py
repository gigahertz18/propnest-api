import uuid

from datetime import datetime
from pydantic import Field
from app.core.schemas.base import BaseResponse


class ReceiptTemplateResponse(BaseResponse):
    id: uuid.UUID
    name: str
    property_id: uuid.UUID | None
    file_url: str = Field(description="Internal storage reference - not a public or directly fetchable URL.")
    is_active: bool
    created_at: datetime
    updated_at: datetime
