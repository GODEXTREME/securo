import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.receipt import ReceiptRead


class CaptureTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    #: The first characters of the secret — enough to tell two apart,
    #: useless on its own.
    prefix: str
    label: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None


class CaptureTokenCreate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=80)


class CaptureTokenCreated(BaseModel):
    token: CaptureTokenRead
    #: Shown once. Only its hash is stored.
    secret: str


class CaptureResponse(BaseModel):
    receipt: ReceiptRead
