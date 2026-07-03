import uuid
from datetime import date as _Date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class SinkingFundCreate(BaseModel):
    name: str
    target_amount: Decimal
    current_amount: Decimal = Decimal("0")
    currency: str = "USD"
    target_date: Optional[_Date] = None
    monthly_contribution: Optional[Decimal] = None
    account_id: Optional[uuid.UUID] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class SinkingFundUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[Decimal] = None
    current_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    target_date: Optional[_Date] = None
    monthly_contribution: Optional[Decimal] = None
    account_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("active", "completed", "archived"):
            raise ValueError("status must be active, completed, or archived")
        return v


class ContributionRequest(BaseModel):
    amount: Decimal  # positive to deposit, negative to withdraw


class SinkingFundRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    target_amount: Decimal
    current_amount: Decimal
    currency: str
    target_date: Optional[_Date] = None
    monthly_contribution: Optional[Decimal] = None
    account_id: Optional[uuid.UUID] = None
    status: str
    icon: Optional[str] = None
    color: Optional[str] = None
    position: int
    created_at: datetime
    updated_at: datetime

    # Computed
    percentage: float = 0
    suggested_monthly: Optional[float] = None
    months_remaining: Optional[int] = None
    account_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
