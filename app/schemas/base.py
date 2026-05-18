from datetime import date, datetime
from pydantic import BaseModel


class BaseResponse(BaseModel):
    model_config = {
        "from_attributes": True,
        "json_encoders": {
            datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S"),
            date: lambda v: v.strftime("%Y-%m-%d"),
        },
    }  # Allows reading from SQLAlchemy model
