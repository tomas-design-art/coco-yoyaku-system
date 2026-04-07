from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Menu(Base):
    __tablename__ = "menus"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    is_duration_variable = Column(Boolean, nullable=False, default=False, server_default="false")
    max_duration_minutes = Column(Integer, nullable=True)
    price = Column(Integer, nullable=True)
    color_id = Column(Integer, ForeignKey("reservation_colors.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    color = relationship("ReservationColor", backref="menus", lazy="joined")
