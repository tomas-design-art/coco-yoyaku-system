from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ReservationSeries(Base):
    __tablename__ = "reservation_series"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    practitioner_id = Column(Integer, ForeignKey("practitioners.id"), nullable=False)
    menu_id = Column(Integer, ForeignKey("menus.id"), nullable=True)
    color_id = Column(Integer, ForeignKey("reservation_colors.id"), nullable=True)
    start_time = Column(String(5), nullable=False, comment="HH:MM")
    duration_minutes = Column(Integer, nullable=False)
    frequency = Column(String(20), nullable=False, comment="weekly/biweekly/monthly")
    channel = Column(String(20), nullable=False, default="PHONE")
    notes = Column(Text, nullable=True)
    remaining_count = Column(Integer, nullable=False)
    total_created = Column(Integer, nullable=False, default=0)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient = relationship("Patient")
    practitioner = relationship("Practitioner")
    menu = relationship("Menu")
    color = relationship("ReservationColor")
    reservations = relationship("Reservation", back_populates="series")
