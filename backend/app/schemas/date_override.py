"""個別日付オーバーライド スキーマ"""
from pydantic import BaseModel, model_validator
from datetime import date, datetime
from typing import Optional


class DateOverrideCreate(BaseModel):
    date: date
    is_open: bool
    open_time: Optional[str] = None
    close_time: Optional[str] = None
    label: Optional[str] = None

    @model_validator(mode="after")
    def validate_times(self):
        if self.is_open:
            if not self.open_time or not self.close_time:
                raise ValueError("営業日の場合は開院・閉院時間を指定してください")
            if self.close_time <= self.open_time:
                raise ValueError("閉院時間は開院時間より後に設定してください")
        return self


class DateOverrideUpdate(BaseModel):
    is_open: bool
    open_time: Optional[str] = None
    close_time: Optional[str] = None
    label: Optional[str] = None

    @model_validator(mode="after")
    def validate_times(self):
        if self.is_open:
            if not self.open_time or not self.close_time:
                raise ValueError("営業日の場合は開院・閉院時間を指定してください")
            if self.close_time <= self.open_time:
                raise ValueError("閉院時間は開院時間より後に設定してください")
        return self


class DateOverrideResponse(BaseModel):
    id: int
    date: date
    is_open: bool
    open_time: Optional[str]
    close_time: Optional[str]
    label: Optional[str]
    updated_at: datetime

    model_config = {"from_attributes": True}
