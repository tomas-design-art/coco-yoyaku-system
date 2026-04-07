"""シャドーモード解析ログ"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database import Base


class ShadowLog(Base):
    __tablename__ = "shadow_logs"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(100), nullable=False, index=True)
    display_name = Column(String(200), nullable=True)
    raw_message = Column(Text, nullable=False)
    has_reservation_intent = Column(Boolean, nullable=False, default=False)
    analysis_result = Column(JSONB, nullable=True)
    notified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
