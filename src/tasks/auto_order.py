"""Auto-restock task — executes a saved Instamart schedule.

v1 constraints:
- COD only (no Razorpay; user pays Swiggy on delivery)
- Cart bound to address — clear_cart before mutating to avoid SKU mismatch
- checkout is non-idempotent — on 5xx we check get_orders before reporting failure
- Per-user max_auto_charge cap (default ₹1000) to keep parity with Food cap
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def execute_auto_order(self, schedule_id: int) -> None:
    try:
        asyncio.get_event_loop().run_until_complete(_execute_auto_order(schedule_id))
    except Exception as exc:
        logger.exception("Auto-order failed for schedule %s", schedule_id)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 300)


@celery_app.task
def check_due_orders() -> None:
    asyncio.get_event_loop().run_until_complete(_check_due_orders())


async def _check_due_orders() -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Schedule).where(
                Schedule.status == ScheduleStatus.ACTIVE,
                Schedule.next_run <= now,
            )
        )
        schedules = result.scalars().all()
        for sched in schedules:
            execute_auto_order.delay(sched.id)


async def _execute_auto_order(schedule_id: int) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus, FrequencyUnit
    from src.models.order import Order, OrderType, OrderStatus
    from src.models.user import User
    from src.services.swiggy_instamart import SwiggyInstamartClient
    from src.services.swiggy_mcp import SwiggyMCPError
    from src.services import swiggy_auth
    from sqlalchemy import select
    from dateutil.relativedelta import relativedelta

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule or schedule.status != ScheduleStatus.ACTIVE:
            return

        user_result = await db.execute(select(User).where(User.telegram_id == schedule.telegram_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        if not user.swiggy_access_token or swiggy_auth.is_token_expired(user.swiggy_token_expires_at):
            await _notify_user(user, f"🔗 Auto-restock *{schedule.name}* skipped — your Swiggy "
                                     f"session expired. Type /start in the bot to reconnect.")
            _reschedule(schedule)
            await db.commit()
            return

        if not user.swiggy_selected_address_id:
            await _notify_user(user, f"📍 Auto-restock *{schedule.name}* skipped — no delivery "
                                     f"address selected. Use /settings to pick one.")
            _reschedule(schedule)
            await db.commit()
            return

        client = SwiggyInstamartClient()
        token = user.swiggy_access_token
        address_id = user.swiggy_selected_address_id

        # Build cart from saved schedule items (item_id should be a spinId)
        cart_items = [{"spinId": it.item_id, "quantity": it.quantity} for it in schedule.items
                      if it.item_id]
        if not cart_items:
            await _notify_user(user, f"⚠️ *{schedule.name}* has no valid Instamart items. "
                                     f"Edit it via /schedules.")
            _reschedule(schedule)
            await db.commit()
            return

        try:
            # Clear server-side cart so schedule items are the only thing checked out
            await client.clear_cart(token)
            await client.update_cart(token, address_id, cart_items)
            cart = await client.get_cart(token)
        except SwiggyMCPError as e:
            await _notify_user(user, f"⚠️ *{schedule.name}* failed at cart build: {e.message}")
            _reschedule(schedule)
            await db.commit()
            return

        total = _cart_total(cart)
        if total == 0:
            await _notify_user(user, f"⚠️ *{schedule.name}* — none of the items are available. Skipping.")
            _reschedule(schedule)
            await db.commit()
            return

        if total > user.max_auto_charge:
            await _notify_user(
                user,
                f"⚠️ *{schedule.name}* — total ₹{total / 100:.2f} exceeds your "
                f"₹{user.max_auto_charge / 100:.0f} auto-charge cap. Order NOT placed. "
                f"Adjust items via /schedules or raise the cap in /settings.",
            )
            _reschedule(schedule)
            await db.commit()
            return

        try:
            checkout_resp = await client.checkout(token, address_id, "COD")
            swiggy_order_id = _extract_order_id(checkout_resp)
        except SwiggyMCPError as e:
            # Non-idempotent recovery: check if it placed anyway
            await asyncio.sleep(3)
            try:
                orders = await client.get_orders(token, count=1, active_only=True)
                latest = (orders.get("orders") or [None])[0] if isinstance(orders, dict) else None
            except Exception:
                latest = None
            if latest:
                swiggy_order_id = _extract_order_id(latest) or "unknown"
                logger.warning("Schedule %s — checkout 5xx but order found in get_orders",
                               schedule_id)
            else:
                await _notify_user(user, f"⚠️ *{schedule.name}* checkout failed: {e.message}")
                _reschedule(schedule)
                await db.commit()
                return

        db.add(Order(
            telegram_id=user.telegram_id,
            type=OrderType.GROCERY,
            swiggy_order_id=swiggy_order_id,
            schedule_id=schedule.id,
            status=OrderStatus.PLACED,
            items=[{"spinId": it.item_id, "name": it.name, "qty": it.quantity}
                   for it in schedule.items],
            subtotal=total,
            delivery_fee=0,
            total=total,
            payment_method="COD",
        ))

        _reschedule(schedule)
        await db.commit()

        await _notify_user(
            user,
            f"✅ *{schedule.name}* — order placed (COD ₹{total / 100:.2f}).\n"
            f"Next run: {schedule.next_run.strftime('%d %b %Y')}",
        )


def _reschedule(schedule) -> None:
    from src.models.schedule import FrequencyUnit
    from dateutil.relativedelta import relativedelta

    now = datetime.now(timezone.utc)
    if schedule.freq_unit == FrequencyUnit.DAYS:
        schedule.next_run = now + timedelta(days=schedule.freq_value)
    elif schedule.freq_unit == FrequencyUnit.WEEKS:
        schedule.next_run = now + timedelta(weeks=schedule.freq_value)
    elif schedule.freq_unit == FrequencyUnit.MONTHS:
        schedule.next_run = now + relativedelta(months=schedule.freq_value)


def _cart_total(cart) -> int:
    if not isinstance(cart, dict):
        return 0
    for key in ("total", "grandTotal", "billTotal", "totalAmount"):
        v = cart.get(key)
        if isinstance(v, (int, float)):
            return int(v) if v > 1000 else int(v * 100)
    total = 0
    for it in cart.get("items", []):
        price = it.get("price", 0) or it.get("totalPrice", 0)
        qty = it.get("quantity", 1)
        total += int(price * qty) if price > 1000 else int(price * qty * 100)
    return total


def _extract_order_id(response):
    if not isinstance(response, dict):
        return None
    for key in ("orderId", "order_id", "id"):
        if response.get(key):
            return str(response[key])
    return None


async def _notify_user(user, message: str) -> None:
    if not user.telegram_id:
        return
    try:
        from src.adapters.base import OutboundMessage
        from src.adapters.telegram import TelegramAdapter
        from telegram.ext import Application
        from config.settings import settings

        app = Application.builder().token(settings.telegram_bot_token).build()
        await app.initialize()
        adapter = TelegramAdapter(app)
        await adapter.send_message(user.telegram_id, OutboundMessage(text=message))
        await app.shutdown()
    except Exception:
        logger.exception("Failed to notify user %s", user.telegram_id)
