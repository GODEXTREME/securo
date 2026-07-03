import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: str
    severity: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    data_json: Optional[Any] = None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unread: int


class UnreadCount(BaseModel):
    unread: int
