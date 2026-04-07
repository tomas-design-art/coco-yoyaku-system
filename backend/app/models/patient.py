from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Date, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    registration_mode = Column(String(20), nullable=False, default="split", server_default="split")
    last_name = Column(String(100), nullable=True)
    middle_name = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name_kana = Column(String(100), nullable=True)
    first_name_kana = Column(String(100), nullable=True)
    reading = Column(String(200), nullable=True)
    birth_date = Column(Date, nullable=True)
    patient_number = Column(String(50), unique=True, nullable=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    line_id = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    default_menu_id = Column(Integer, ForeignKey("menus.id", ondelete="SET NULL"), nullable=True)
    default_duration = Column(Integer, nullable=True)  # minutes
    preferred_practitioner_id = Column(Integer, ForeignKey("practitioners.id", ondelete="SET NULL"), nullable=True)
    preferred_practitioner = relationship("Practitioner", foreign_keys=[preferred_practitioner_id])
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
