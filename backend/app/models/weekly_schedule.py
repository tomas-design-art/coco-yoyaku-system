from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class WeeklySchedule(Base):
    __tablename__ = "weekly_schedules"

    id = Column(Integer, primary_key=True, index=True)
    day_of_week = Column(Integer, unique=True, nullable=False)  # 0=日, 1=月 ... 6=土
    is_open = Column(Boolean, nullable=False, default=True)
    open_time = Column(String(5), nullable=False, default="09:00")   # HH:MM
    close_time = Column(String(5), nullable=False, default="20:00")  # HH:MM
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
