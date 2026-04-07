from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SettingUpdate(BaseModel):
    value: str


class SettingResponse(BaseModel):
    id: int
    key: str
    value: str
    updated_at: datetime

    model_config = {"from_attributes": True}
