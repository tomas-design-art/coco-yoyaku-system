"""個別日付オーバーライドモデル（特別休診日・特別営業日）"""
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime
from sqlalchemy.sql import func
from app.database import Base


class DateOverride(Base):
    __tablename__ = "date_overrides"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    is_open = Column(Boolean, nullable=False, default=False)
    open_time = Column(String(5), nullable=True)   # "HH:MM" or null
    close_time = Column(String(5), nullable=True)   # "HH:MM" or null
    label = Column(String(100), nullable=True)       # "年末休業", "臨時営業" etc.
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
