from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from ..db.database import Base


class ScheduleStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class FrequencyUnit(str, enum.Enum):
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, ForeignKey("users.telegram_id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    freq_value = Column(Integer, nullable=False)
    freq_unit = Column(Enum(FrequencyUnit), nullable=False)
    anchor_day = Column(String, nullable=True)
    next_run = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(ScheduleStatus), default=ScheduleStatus.ACTIVE)
    reminder_enabled = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    items = relationship("ScheduleItem", back_populates="schedule", cascade="all, delete-orphan")


class ScheduleItem(Base):
    __tablename__ = "schedule_items"

    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False, index=True)
    # For Instamart items, this is the variant spinId. For free-text items
    # awaiting first run, may be the user-typed name.
    item_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit = Column(String, nullable=True)

    schedule = relationship("Schedule", back_populates="items")
