from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class ReservationColorCreate(BaseModel):
    name: str
    color_code: str
    display_order: int = 0
    is_default: bool = False

    @field_validator("color_code")
    @classmethod
    def validate_color_code(cls, v: str) -> str:
        if not v.startswith("#") or len(v) != 7:
            raise ValueError("color_code は #RRGGBB 形式で指定してください")
        return v


class ReservationColorUpdate(BaseModel):
    name: Optional[str] = None
    color_code: Optional[str] = None
    display_order: Optional[int] = None
    is_default: Optional[bool] = None

    @field_validator("color_code")
    @classmethod
    def validate_color_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not v.startswith("#") or len(v) != 7):
            raise ValueError("color_code は #RRGGBB 形式で指定してください")
        return v


class ReservationColorResponse(BaseModel):
    id: int
    name: str
    color_code: str
    display_order: int
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
