from sqlalchemy import Column, Integer, String, DateTime, Enum, JSON
from sqlalchemy.sql import func
import enum

from ..db.database import Base


class OrderType(str, enum.Enum):
    FOOD = "food"
    GROCERY = "grocery"
    DINEOUT = "dineout"


class OrderStatus(str, enum.Enum):
    PENDING_CONFIRMATION = "pending_confirmation"
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, nullable=False, index=True)
    type = Column(Enum(OrderType), nullable=False)
    # Swiggy order ID from place_food_order / checkout response. v1 is COD,
    # so there is no Razorpay or other PSP order id stored.
    swiggy_order_id = Column(String, nullable=True, unique=True)
    schedule_id = Column(Integer, nullable=True)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING_CONFIRMATION)
    items = Column(JSON, nullable=False, default=list)
    subtotal = Column(Integer, nullable=False)       # paise
    delivery_fee = Column(Integer, nullable=False)   # paise
    total = Column(Integer, nullable=False)          # paise
    restaurant_id = Column(String, nullable=True)
    restaurant_name = Column(String, nullable=True)
    payment_method = Column(String, nullable=True, default="COD")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
