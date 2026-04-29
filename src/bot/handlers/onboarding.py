import logging
from typing import Any, Dict

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService

logger = logging.getLogger(__name__)

MAIN_MENU_BUTTONS = [
    [Button("🍔 Order Food", "order_food"), Button("🛒 Order Groceries", "order_grocery")],
    [Button("🔄 Auto-Restock", "schedules"), Button("📦 My Orders", "my_orders")],
    [Button("⚙️ Settings", "settings"), Button("❓ Help", "help")],
]


async def handle_start(user_id: str, adapter: MessagingAdapter, session: SessionService,
                       user_data: Dict[str, Any]) -> None:
    if user_data.get("onboarded"):
        await adapter.send_buttons(user_id, "Welcome back! What would you like to do?", MAIN_MENU_BUTTONS)
        return

    await session.set(user_id, {"state": "ONBOARDING", "step": "location"})
    await adapter.send_message(user_id, OutboundMessage(
        text="👋 Hi! I'm your Swiggy assistant.\n\nI can help you order food, groceries, and set up automatic restocking — all without leaving this chat.\n\nFirst, let's get your location."
    ))
    await adapter.send_location_request(user_id, "📍 Please share your delivery location:")


async def handle_location(user_id: str, lat: float, lng: float,
                          adapter: MessagingAdapter, session: SessionService) -> None:
    await session.update(user_id, {"lat": lat, "lng": lng, "step": "phone"})
    await adapter.send_message(user_id, OutboundMessage(
        text=f"✅ Got your location.\n\nNow please share your phone number to link your Swiggy account:"
    ))


async def handle_phone_otp(user_id: str, phone: str,
                           adapter: MessagingAdapter, session: SessionService) -> None:
    await session.update(user_id, {"phone": phone, "step": "otp"})
    await adapter.send_message(user_id, OutboundMessage(
        text=f"📱 Sending OTP to {phone}... Please enter the 6-digit code:"
    ))


async def complete_onboarding(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    await session.update(user_id, {"state": "IDLE", "onboarded": True})
    await adapter.send_buttons(
        user_id,
        "🎉 You're all set! What would you like to do?",
        MAIN_MENU_BUTTONS,
    )
