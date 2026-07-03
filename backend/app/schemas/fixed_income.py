import uuid
from datetime import date as _Date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

_RATE_KINDS = ("cdi", "prefixed", "ipca_plus")
_LIQUIDITY = ("daily", "maturity")


class FixedIncomeOptionCreate(BaseModel):
    name: str
    institution: Optional[str] = None
    product_type: str = "CDB"
    rate_kind: str = "cdi"
    rate: Decimal
    liquidity: str = "daily"
    maturity_date: Optional[_Date] = None
    min_amount: Optional[Decimal] = None
    tax_exempt: bool = False

    @field_validator("rate_kind")
    @classmethod
    def _rk(cls, v: str) -> str:
        if v not in _RATE_KINDS:
            raise ValueError(f"rate_kind must be one of {_RATE_KINDS}")
        return v

    @field_validator("liquidity")
    @classmethod
    def _lq(cls, v: str) -> str:
        if v not in _LIQUIDITY:
            raise ValueError(f"liquidity must be one of {_LIQUIDITY}")
        return v


class FixedIncomeOptionUpdate(BaseModel):
    name: Optional[str] = None
    institution: Optional[str] = None
    product_type: Optional[str] = None
    rate_kind: Optional[str] = None
    rate: Optional[Decimal] = None
    liquidity: Optional[str] = None
    maturity_date: Optional[_Date] = None
    min_amount: Optional[Decimal] = None
    tax_exempt: Optional[bool] = None

    @field_validator("rate_kind")
    @classmethod
    def _rk(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _RATE_KINDS:
            raise ValueError(f"rate_kind must be one of {_RATE_KINDS}")
        return v

    @field_validator("liquidity")
    @classmethod
    def _lq(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _LIQUIDITY:
            raise ValueError(f"liquidity must be one of {_LIQUIDITY}")
        return v


class FixedIncomeOptionRead(BaseModel):
    id: uuid.UUID
    name: str
    institution: Optional[str] = None
    product_type: str
    rate_kind: str
    rate: Decimal
    liquidity: str
    maturity_date: Optional[_Date] = None
    min_amount: Optional[Decimal] = None
    tax_exempt: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
