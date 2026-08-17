import uuid

from datetime import datetime

from app.schemas.base import BaseResponse


class ReceiptTemplateResponse(BaseResponse):
    id: uuid.UUID
    name: str
    property_id: uuid.UUID | None
    file_url: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
