from sqlalchemy import Column, Integer, String, DateTime, Enum, JSON
from sqlalchemy.sql import func
import enum

from ..db.database import Base


class OrderType(str, enum.Enum):
    FOOD = "food"
    GROCERY = "grocery"


class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_phone = Column(String, nullable=False, index=True)
    type = Column(Enum(OrderType), nullable=False)
    swiggy_order_id = Column(String, nullable=True, unique=True)
    razorpay_order_id = Column(String, nullable=True)
    schedule_id = Column(Integer, nullable=True)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    items = Column(JSON, nullable=False, default=list)
    subtotal = Column(Integer, nullable=False)       # paise
    delivery_fee = Column(Integer, nullable=False)   # paise
    total = Column(Integer, nullable=False)          # paise
    restaurant_id = Column(String, nullable=True)
    restaurant_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
