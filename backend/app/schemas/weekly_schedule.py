from pydantic import BaseModel
from datetime import datetime


class WeeklyScheduleUpdate(BaseModel):
    is_open: bool
    open_time: str
    close_time: str


class WeeklyScheduleResponse(BaseModel):
    id: int
    day_of_week: int
    is_open: bool
    open_time: str
    close_time: str
    updated_at: datetime

    model_config = {"from_attributes": True}
