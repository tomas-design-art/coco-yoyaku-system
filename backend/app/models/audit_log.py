from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    operator = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    target_id = Column(Integer, nullable=True)
    detail = Column(JSON, nullable=True)
