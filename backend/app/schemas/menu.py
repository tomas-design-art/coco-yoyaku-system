from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ColorBrief(BaseModel):
    id: int
    name: str
    color_code: str
    model_config = {"from_attributes": True}


class MenuCreate(BaseModel):
    name: str
    duration_minutes: int
    is_duration_variable: bool = False
    max_duration_minutes: Optional[int] = None
    price: Optional[int] = None
    color_id: Optional[int] = None
    is_active: bool = True
    display_order: int = 0


class MenuUpdate(BaseModel):
    name: Optional[str] = None
    duration_minutes: Optional[int] = None
    is_duration_variable: Optional[bool] = None
    max_duration_minutes: Optional[int] = None
    price: Optional[int] = None
    color_id: Optional[int] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class MenuResponse(BaseModel):
    id: int
    name: str
    duration_minutes: int
    is_duration_variable: bool
    max_duration_minutes: Optional[int] = None
    price: Optional[int] = None
    color_id: Optional[int] = None
    color: Optional[ColorBrief] = None
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
