import uuid

from datetime import datetime

from app.schemas.base import BaseResponse


class ReceiptResponse(BaseResponse):
    """Returned to the client — a Receipt is append-only, so there is no
    Create/Update request schema: every field is server-derived from the
    `payment_id` path param."""

    id: uuid.UUID
    receipt_number: int
    payment_id: uuid.UUID
    document_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
