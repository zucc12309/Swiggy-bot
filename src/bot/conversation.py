import logging
from dataclasses import dataclass
from typing import Optional

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.bot.handlers import food_order, grocery_order, onboarding, payment, schedules
from src.services.session import SessionService

logger = logging.getLogger(__name__)

CANCEL_PHRASES = {"cancel", "/cancel", "stop", "quit", "exit"}
FOOD_TRIGGERS = {"order food", "food", "hungry", "eat", "restaurant", "biryani", "pizza", "burger"}
GROCERY_TRIGGERS = {"order groceries", "groceries", "instamart", "grocery", "get milk", "vegetables"}
SCHEDULE_TRIGGERS = {"auto restock", "schedule", "auto-restock", "set up restock", "create schedule", "restock"}

MAIN_MENU_BUTTONS = [
    [Button("🍔 Order Food", "order_food"), Button("🛒 Order Groceries", "order_grocery")],
    [Button("🔄 My Schedules", "schedules"), Button("📦 My Orders", "my_orders")],
    [Button("⚙️ Settings", "settings"), Button("❓ Help", "help")],
]


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
            await self._adapter.send_message(msg.user_id, OutboundMessage(
                text="⚠️ Something went wrong. Please try again or type /menu to return to the main menu."
            ))

    async def _dispatch(self, msg: IncomingMessage) -> None:
        user_id = msg.user_id
        state = await self._session.get_state(user_id)
        text = (msg.text or "").strip()
        text_lower = text.lower()
        cb = msg.callback_data or ""

        # Global cancel
        if text_lower in CANCEL_PHRASES or cb == "cancel_order":
            await self._session.delete(user_id)
            await self._adapter.send_buttons(user_id, "↩️ Cancelled. What would you like to do?",
                                             MAIN_MENU_BUTTONS)
            return

        # Global commands
        if text_lower in {"/start", "start", "hi", "hello"}:
            sess = await self._session.get(user_id)
            await onboarding.handle_start(user_id, self._adapter, self._session, sess or {})
            return

        if text_lower in {"/menu", "menu", "main menu"}:
            await self._adapter.send_buttons(user_id, "What would you like to do?", MAIN_MENU_BUTTONS)
            return

        if text_lower in {"/orders", "my orders", "order history"}:
            await self._handle_my_orders(user_id)
            return

        if text_lower in {"/schedules", "my schedules", "show schedules", "show my schedules"}:
            await schedules.handle_list_schedules(user_id, self._adapter, self._session)
            return

        if text_lower in {"/help", "help"}:
            await self._send_help(user_id)
            return

        if text_lower in {"/settings", "settings"}:
            await self._send_settings(user_id)
            return

        # Callback routing (platform-agnostic)
        if cb:
            await self._handle_callback(user_id, cb, state)
            return

        # State-based routing
        if state == "ONBOARDING":
            await self._handle_onboarding(msg, text)
        elif state == "FOOD_ORDER":
            await food_order.handle_food_search(user_id, text, self._adapter, self._session)
        elif state == "GROCERY_ORDER":
            await grocery_order.handle_grocery_message(user_id, text, self._adapter, self._session)
        elif state == "SCHEDULE_CREATE":
            await self._handle_schedule_create(text, user_id)
        elif state == "SCHEDULE_EDIT":
            await self._handle_schedule_edit(text, user_id)
        elif state == "PAYMENT_PENDING":
            await self._adapter.send_message(user_id, OutboundMessage(
                text="⏳ Waiting for payment. Complete the payment via the link above, or type /cancel to exit."
            ))
        else:
            await self._handle_idle(user_id, text_lower)

    async def _handle_callback(self, user_id: str, cb: str, state: str) -> None:
        # Navigation
        if cb == "order_food":
            await self._session.update(user_id, {"state": "FOOD_ORDER"})
            await self._adapter.send_message(user_id, OutboundMessage(
                text="🍔 What are you in the mood for? (e.g. *biryani*, *pizza*, *South Indian*)"
            ))
        elif cb == "order_grocery":
            await self._session.update(user_id, {"state": "GROCERY_ORDER", "step": "search", "grocery_cart": []})
            await self._adapter.send_message(user_id, OutboundMessage(
                text="🛒 What would you like to order? (e.g. *milk*, *tomatoes*, *rice*)"
            ))
        elif cb == "schedules":
            await schedules.handle_list_schedules(user_id, self._adapter, self._session)
        elif cb == "my_orders":
            await self._handle_my_orders(user_id)
        elif cb == "settings":
            await self._send_settings(user_id)
        elif cb == "help":
            await self._send_help(user_id)

        # Food order callbacks
        elif cb.startswith("rest_"):
            await food_order.handle_restaurant_select(cb[5:], cb[5:], self._adapter, self._session)
        elif cb.startswith("cat_"):
            await food_order.handle_category_select(user_id, cb[4:], self._adapter, self._session)
        elif cb.startswith("item_"):
            await food_order.handle_item_add(user_id, cb[5:], self._adapter, self._session)
        elif cb == "checkout":
            await food_order.handle_checkout(user_id, self._adapter, self._session)
        elif cb == "edit_cart":
            await food_order.handle_edit_cart(user_id, self._adapter, self._session)
        elif cb.startswith("remove_item_"):
            await food_order.handle_remove_item(user_id, cb[12:], self._adapter, self._session)

        # Grocery callbacks
        elif cb.startswith("prod_"):
            await grocery_order.handle_grocery_callback(user_id, cb, self._adapter, self._session)
        elif cb.startswith("unit_") or cb in {"grocery_checkout", "grocery_more", "edit_grocery_cart"}:
            await grocery_order.handle_grocery_callback(user_id, cb, self._adapter, self._session)

        # Payment
        elif cb == "confirm_pay":
            await payment.handle_confirm_pay(user_id, self._adapter, self._session)

        # Schedule callbacks
        elif cb == "confirm_schedule":
            await self._save_schedule(user_id)
        elif cb == "cancel_schedule":
            await self._session.update(user_id, {"state": "IDLE"})
            await self._adapter.send_buttons(user_id, "Schedule cancelled.", MAIN_MENU_BUTTONS)
        elif cb == "edit_items_again":
            await self._session.update(user_id, {"step": "items"})
            sess = await self._session.get(user_id)
            items = sess.get("schedule_items", [])
            await self._adapter.send_message(user_id, OutboundMessage(
                text=f"Current items: {', '.join(i['name'] for i in items)}\n\nAdd more or type *done*."
            ))
        elif cb.startswith("edit_sched_"):
            schedule_id = int(cb.split("_")[2])
            await schedules.handle_schedule_edit_start(user_id, schedule_id, self._adapter, self._session)
        elif cb == "sched_pause":
            await schedules.handle_schedule_control(user_id, "pause", self._adapter, self._session)
        elif cb == "sched_cancel":
            await schedules.handle_schedule_control(user_id, "cancel", self._adapter, self._session)

        # Reminder response callbacks
        elif cb.startswith("remind_ok_"):
            schedule_id = int(cb.split("_")[2])
            await schedules.handle_reminder_response(user_id, "ok", schedule_id, self._adapter, self._session)
        elif cb.startswith("remind_skip_"):
            schedule_id = int(cb.split("_")[2])
            await schedules.handle_reminder_response(user_id, "skip", schedule_id, self._adapter, self._session)
        elif cb.startswith("remind_pause_"):
            schedule_id = int(cb.split("_")[2])
            await schedules.handle_reminder_response(user_id, "pause", schedule_id, self._adapter, self._session)
        elif cb.startswith("remind_edit_"):
            schedule_id = int(cb.split("_")[2])
            await schedules.handle_reminder_response(user_id, "edit", schedule_id, self._adapter, self._session)

    async def _handle_onboarding(self, msg: IncomingMessage, text: str) -> None:
        sess = await self._session.get(msg.user_id)
        step = (sess or {}).get("step")
        if step == "location" and msg.lat is not None:
            await onboarding.handle_location(msg.user_id, msg.lat, msg.lng,
                                             self._adapter, self._session)
        elif step == "phone":
            await onboarding.handle_phone_otp(msg.user_id, text, self._adapter, self._session)
        elif step == "otp":
            await onboarding.complete_onboarding(msg.user_id, self._adapter, self._session)

    async def _handle_schedule_create(self, text: str, user_id: str) -> None:
        sess = await self._session.get(user_id)
        step = (sess or {}).get("step")
        if step == "name":
            await schedules.handle_schedule_name(user_id, text, self._adapter, self._session)
        elif step == "frequency":
            await schedules.handle_schedule_frequency(user_id, text, self._adapter, self._session)
        elif step == "items":
            await schedules.handle_schedule_items(user_id, text, self._adapter, self._session)

    async def _handle_schedule_edit(self, text: str, user_id: str) -> None:
        text_lower = text.lower()
        if text_lower == "skip":
            await schedules.handle_schedule_control(user_id, "skip", self._adapter, self._session)
        elif text_lower == "pause":
            await schedules.handle_schedule_control(user_id, "pause", self._adapter, self._session)
        elif text_lower == "resume":
            await schedules.handle_schedule_control(user_id, "resume", self._adapter, self._session)
        elif text_lower in {"cancel schedule", "delete schedule"}:
            await schedules.handle_schedule_control(user_id, "cancel", self._adapter, self._session)
        elif text_lower.startswith("delay"):
            parts = text_lower.split()
            days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            await self._delay_schedule(user_id, days)

    async def _delay_schedule(self, user_id: str, days: int) -> None:
        from src.db.database import AsyncSessionLocal
        from src.models.schedule import Schedule
        sess = await self._session.get(user_id)
        schedule_id = (sess or {}).get("editing_schedule_id")
        if not schedule_id:
            return
        from datetime import timedelta
        async with AsyncSessionLocal() as db:
            sched = await db.get(Schedule, schedule_id)
            if sched:
                sched.next_run = sched.next_run + timedelta(days=days)
                await db.commit()
                await self._adapter.send_message(user_id, OutboundMessage(
                    text=f"⏩ Next run delayed by {days} day(s). New date: {sched.next_run.strftime('%d %b %Y')}."
                ))

    async def _save_schedule(self, user_id: str) -> None:
        from src.db.database import AsyncSessionLocal
        from src.models.schedule import Schedule, ScheduleItem, FrequencyUnit
        from datetime import datetime

        sess = await self._session.get(user_id)
        phone = (sess or {}).get("phone", user_id)
        name = (sess or {}).get("schedule_name", "My Schedule")
        freq_value = (sess or {}).get("freq_value", 1)
        freq_unit = (sess or {}).get("freq_unit", "weeks")
        anchor_day = (sess or {}).get("anchor_day")
        next_run_str = (sess or {}).get("next_run")
        items = (sess or {}).get("schedule_items", [])
        next_run = datetime.fromisoformat(next_run_str) if next_run_str else datetime.now()

        async with AsyncSessionLocal() as db:
            schedule = Schedule(
                user_phone=phone,
                name=name,
                freq_value=freq_value,
                freq_unit=FrequencyUnit(freq_unit),
                anchor_day=anchor_day,
                next_run=next_run,
            )
            db.add(schedule)
            await db.flush()
            for item in items:
                db.add(ScheduleItem(
                    schedule_id=schedule.id,
                    item_id=item.get("id", item["name"]),
                    name=item["name"],
                    quantity=item.get("qty", 1),
                    unit=item.get("unit", "pcs"),
                ))
            await db.commit()

        await self._session.update(user_id, {"state": "IDLE"})
        await self._adapter.send_message(user_id, OutboundMessage(
            text=f"✅ *{name}* saved! Your first order will be placed on "
                 f"{next_run.strftime('%d %b %Y')}.\n\n"
                 f"You'll get a reminder {(sess or {}).get('reminder_lead_hours', 12)} hours before. "
                 f"Use /schedules to view or edit it anytime."
        ))

    async def _handle_idle(self, user_id: str, text_lower: str) -> None:
        if any(t in text_lower for t in FOOD_TRIGGERS):
            await self._session.update(user_id, {"state": "FOOD_ORDER"})
            await food_order.handle_food_search(user_id, text_lower, self._adapter, self._session)
        elif any(t in text_lower for t in GROCERY_TRIGGERS):
            await self._session.update(user_id, {"state": "GROCERY_ORDER", "step": "search", "grocery_cart": []})
            await grocery_order.handle_grocery_start(user_id, text_lower, self._adapter, self._session)
        elif any(t in text_lower for t in SCHEDULE_TRIGGERS):
            await schedules.handle_create_schedule_start(user_id, self._adapter, self._session)
        else:
            await self._adapter.send_buttons(
                user_id,
                "What would you like to do? Tap a button or type a request:",
                MAIN_MENU_BUTTONS,
            )

    async def _handle_my_orders(self, user_id: str) -> None:
        from src.db.database import AsyncSessionLocal
        from src.models.order import Order
        from sqlalchemy import select, desc

        sess = await self._session.get(user_id)
        phone = (sess or {}).get("phone", user_id)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Order).where(Order.user_phone == phone).order_by(desc(Order.created_at)).limit(5)
            )
            orders = result.scalars().all()

        if not orders:
            await self._adapter.send_message(user_id, OutboundMessage(text="You have no orders yet."))
            return

        lines = []
        for o in orders:
            status_emoji = {"delivered": "✅", "placed": "🔄", "confirmed": "🔄",
                            "picked_up": "🛵", "cancelled": "❌", "failed": "❌"}.get(o.status.value, "⏳")
            lines.append(f"{status_emoji} *{o.type.value.title()}* — ₹{o.total / 100:.0f} — {o.created_at.strftime('%d %b %H:%M')}")

        await self._adapter.send_message(user_id, OutboundMessage(
            text="📦 *Recent Orders*\n\n" + "\n".join(lines)
        ))

    async def _send_help(self, user_id: str) -> None:
        await self._adapter.send_message(user_id, OutboundMessage(
            text="❓ *Help*\n\n"
                 "/start — Return to main menu\n"
                 "/menu — Show all options\n"
                 "/orders — View recent orders\n"
                 "/schedules — Manage auto-restock schedules\n"
                 "/settings — Update address, reminders, budget\n"
                 "/cancel — Exit current flow\n\n"
                 "Or just type what you want:\n"
                 "• *order food* — Search restaurants\n"
                 "• *order groceries* — Shop on Instamart\n"
                 "• *auto restock* — Set up a recurring order\n"
                 "• *my orders* — View order history"
        ))

    async def _send_settings(self, user_id: str) -> None:
        await self._adapter.send_buttons(
            user_id,
            "⚙️ *Settings*",
            [
                [Button("📍 Update Address", "update_address")],
                [Button("⏰ Reminder Timing", "update_reminder")],
                [Button("💳 Payment Method", "update_payment")],
            ],
        )
