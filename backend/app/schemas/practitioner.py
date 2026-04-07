from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class PractitionerCreate(BaseModel):
    name: str
    role: str = "施術者"
    is_active: bool = True
    is_visible: bool = True
    display_order: int = 0


class PractitionerUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_visible: Optional[bool] = None
    display_order: Optional[int] = None


class PractitionerResponse(BaseModel):
    id: int
    name: str
    role: str
    is_active: bool
    is_visible: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
