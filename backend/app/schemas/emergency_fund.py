import uuid
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class EmergencyFundUpdate(BaseModel):
    target_months: Optional[int] = None
    current_amount: Optional[Decimal] = None
    account_id: Optional[uuid.UUID] = None
    monthly_contribution: Optional[Decimal] = None


class EmergencyFundRead(BaseModel):
    target_months: int
    current_amount: float
    account_id: Optional[uuid.UUID] = None
    account_name: Optional[str] = None
    monthly_contribution: Optional[float] = None
    currency: str

    # Computed
    avg_monthly_expense: float
    target_amount: float
    saved_amount: float
    progress_pct: float
    months_covered: float
    shortfall: float
    months_to_complete: Optional[int] = None
