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
    telegram_id = Column(String, nullable=False, index=True)
    # Instamart variant spinId — what gets passed to update_cart
    product_spin_id = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    address_id = Column(String, nullable=False)   # alerts are address-scoped (Instamart)
    target_price = Column(Integer, nullable=False)
    previous_price = Column(Integer, nullable=False)
    status = Column(Enum(PriceAlertStatus), default=PriceAlertStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    fired_at = Column(DateTime(timezone=True), nullable=True)
