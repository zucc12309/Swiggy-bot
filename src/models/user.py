from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from ..db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)

    # Swiggy OAuth — token issued per user via PKCE flow, 5-day lifetime
    swiggy_oauth_client_id = Column(String, nullable=True)
    swiggy_access_token = Column(String, nullable=True)
    swiggy_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    swiggy_selected_address_id = Column(String, nullable=True)
    swiggy_selected_address_label = Column(String, nullable=True)
    swiggy_selected_lat = Column(String, nullable=True)
    swiggy_selected_lng = Column(String, nullable=True)

    # Bot preferences
    reminder_lead_hours = Column(Integer, default=12)
    # Per-auto-restock cap. Swiggy Food caps at ₹1000 (100_000 paise) in v1;
    # Instamart has no MCP-side cap. Keep below 100_000 for cross-server safety.
    max_auto_charge = Column(Integer, default=100000)  # paise, default ₹1000
    monthly_budget = Column(Integer, nullable=True)    # paise; null = no budget
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
