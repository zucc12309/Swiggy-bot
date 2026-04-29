from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from ..db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    telegram_id = Column(String, unique=True, nullable=True, index=True)
    name = Column(String, nullable=True)
    address = Column(String, nullable=True)
    latitude = Column(String, nullable=True)
    longitude = Column(String, nullable=True)
    payment_method_id = Column(String, nullable=True)
    reminder_lead_hours = Column(Integer, default=12)
    max_auto_charge = Column(Integer, default=200000)  # paise, default ₹2000
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
