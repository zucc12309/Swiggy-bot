from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.sql import func
import enum

from ..db.database import Base


class PriceAlertStatus(str, enum.Enum):
    ACTIVE = "active"
    FIRED = "fired"
    SNOOZED = "snoozed"
    DELETED = "deleted"


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True)
    user_phone = Column(String, nullable=False, index=True)
    product_id = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    target_price = Column(Integer, nullable=False)   # paise
    previous_price = Column(Integer, nullable=False) # paise at time of alert creation
    status = Column(Enum(PriceAlertStatus), default=PriceAlertStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    fired_at = Column(DateTime(timezone=True), nullable=True)
