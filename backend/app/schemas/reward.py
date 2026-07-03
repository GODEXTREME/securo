import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RewardRuleCreate(BaseModel):
    account_id: uuid.UUID
    category_id: Optional[uuid.UUID] = None
    rate: Decimal
    name: Optional[str] = None


class RewardRuleUpdate(BaseModel):
    account_id: Optional[uuid.UUID] = None
    category_id: Optional[uuid.UUID] = None
    rate: Optional[Decimal] = None
    name: Optional[str] = None


class RewardRuleRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    category_id: Optional[uuid.UUID] = None
    rate: Decimal
    name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Computed
    account_name: Optional[str] = None
    category_name: Optional[str] = None
    category_color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
