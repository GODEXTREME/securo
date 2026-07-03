import uuid
from datetime import date as _Date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

_KINDS = ("dividend", "jcp", "rent", "interest", "other")


class AssetIncomeCreate(BaseModel):
    asset_id: uuid.UUID
    date: _Date
    amount: Decimal
    currency: str = "USD"
    kind: str = "dividend"
    note: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}")
        return v


class AssetIncomeUpdate(BaseModel):
    asset_id: Optional[uuid.UUID] = None
    date: Optional[_Date] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    kind: Optional[str] = None
    note: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}")
        return v


class AssetIncomeRead(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    date: _Date
    amount: Decimal
    currency: str
    kind: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Computed
    asset_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
