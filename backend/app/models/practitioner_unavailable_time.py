"""施術者の時間帯休み（部分的な不在）"""
from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, func, UniqueConstraint
from app.database import Base


class PractitionerUnavailableTime(Base):
    __tablename__ = "practitioner_unavailable_times"

    id = Column(Integer, primary_key=True, index=True)
    practitioner_id = Column(Integer, ForeignKey("practitioners.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(String(5), nullable=False)   # "HH:MM"
    end_time = Column(String(5), nullable=False)      # "HH:MM"
    reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
