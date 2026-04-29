import logging
from dataclasses import dataclass
from typing import Optional

from src.adapters.base import MessagingAdapter
from src.bot.handlers import food_order, onboarding, schedules
from src.services.session import SessionService

logger = logging.getLogger(__name__)

CANCEL_PHRASES = {"cancel", "/cancel", "stop", "quit", "exit"}
FOOD_TRIGGERS = {"order food", "food", "hungry", "eat", "restaurant"}
GROCERY_TRIGGERS = {"order groceries", "groceries", "instamart", "grocery"}
SCHEDULE_TRIGGERS = {"auto restock", "schedule", "auto-restock", "set up restock", "create schedule"}


@dataclass
class IncomingMessage:
    user_id: str
    text: Optional[str]
    callback_data: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class ConversationManager:
    def __init__(self, adapter: MessagingAdapter, session: SessionService) -> None:
        self._adapter = adapter
        self._session = session

    async def handle(self, msg: IncomingMessage) -> None:
        try:
            await self._dispatch(msg)
        except Exception:
            logger.exception("Unhandled error for user %s", msg.user_id)
            from src.adapters.base import OutboundMessage
            await self._adapter.send_message(msg.user_id, OutboundMessage(
                text="⚠️ Something went wrong. Please try again or type /menu to return to the main menu."
            ))

    async def _dispatch(self, msg: IncomingMessage) -> None:
        user_id = msg.user_id
        state = await self._session.get_state(user_id)
        text = (msg.text or "").strip().lower()

        if text in CANCEL_PHRASES:
            await self._session.delete(user_id)
            from src.adapters.base import OutboundMessage
            await self._adapter.send_message(user_id, OutboundMessage(text="↩️ Cancelled. Type /menu to start over."))
            return

        if text in {"/start", "start", "hi", "hello"}:
            sess = await self._session.get(user_id)
            await onboarding.handle_start(user_id, self._adapter, self._session, sess or {})
            return

        if state == "ONBOARDING":
            await self._handle_onboarding(msg, text)
        elif state == "FOOD_ORDER":
            await self._handle_food_order(msg, text)
        elif state == "SCHEDULE_CREATE":
            await self._handle_schedule_create(msg, text)
        elif state == "IDLE":
            await self._handle_idle(msg, text)

    async def _handle_onboarding(self, msg: IncomingMessage, text: str) -> None:
        sess = await self._session.get(msg.user_id)
        step = sess.get("step") if sess else None
        if step == "location" and msg.lat:
            await onboarding.handle_location(msg.user_id, msg.lat, msg.lng, self._adapter, self._session)
        elif step == "phone":
            await onboarding.handle_phone_otp(msg.user_id, text, self._adapter, self._session)
        elif step == "otp":
            await onboarding.complete_onboarding(msg.user_id, self._adapter, self._session)

    async def _handle_food_order(self, msg: IncomingMessage, text: str) -> None:
        cb = msg.callback_data or ""
        if cb.startswith("rest_"):
            await food_order.handle_restaurant_select(msg.user_id, cb[5:], self._adapter, self._session)
        elif cb == "checkout":
            await food_order.handle_checkout(msg.user_id, self._adapter, self._session)
        else:
            await food_order.handle_food_search(msg.user_id, text, self._adapter, self._session)

    async def _handle_schedule_create(self, msg: IncomingMessage, text: str) -> None:
        sess = await self._session.get(msg.user_id)
        step = sess.get("step") if sess else None
        if step == "name":
            await schedules.handle_schedule_name(msg.user_id, text, self._adapter, self._session)
        elif step == "frequency":
            await schedules.handle_schedule_frequency(msg.user_id, text, self._adapter, self._session)
        elif step == "items":
            await schedules.handle_schedule_items(msg.user_id, text, self._adapter, self._session)

    async def _handle_idle(self, msg: IncomingMessage, text: str) -> None:
        if any(t in text for t in FOOD_TRIGGERS):
            await self._session.update(msg.user_id, {"state": "FOOD_ORDER"})
            await food_order.handle_food_search(msg.user_id, text, self._adapter, self._session)
        elif any(t in text for t in SCHEDULE_TRIGGERS):
            await schedules.handle_create_schedule_start(msg.user_id, self._adapter, self._session)
        else:
            from src.adapters.base import OutboundMessage
            await self._adapter.send_message(msg.user_id, OutboundMessage(
                text="Type /menu to see all options, or tell me what you'd like — e.g. *order food*, *order groceries*, *auto restock*."
            ))
