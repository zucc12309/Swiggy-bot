import asyncio
import logging
from datetime import datetime, timezone

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
            logger.info("Queued auto-order for schedule %s", sched.id)


async def _execute_auto_order(schedule_id: int) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus, FrequencyUnit
    from src.models.order import Order, OrderType, OrderStatus
    from src.models.user import User
    from src.services.swiggy_instamart import SwiggyInstamartClient
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule or schedule.status != ScheduleStatus.ACTIVE:
            return

        user_result = await db.execute(select(User).where(User.phone == schedule.user_phone))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        client = SwiggyInstamartClient()
        cart_items = []
        total = 0

        for sched_item in schedule.items:
            try:
                product = await client.get_product(sched_item.item_id)
                if not product:
                    logger.warning("Item %s unavailable for schedule %s", sched_item.name, schedule_id)
                    await _notify_user(user, f"⚠️ *{sched_item.name}* is currently unavailable and was skipped.")
                    continue

                price = product["price"] * sched_item.quantity
                cart_items.append({
                    "id": sched_item.item_id,
                    "name": sched_item.name,
                    "qty": sched_item.quantity,
                    "unit": sched_item.unit,
                    "price": product["price"],
                })
                total += price
            except Exception:
                logger.exception("Failed to fetch product %s", sched_item.item_id)

        if not cart_items:
            await _notify_user(user, f"⚠️ Auto-restock *{schedule.name}* skipped — no items were available.")
            _reschedule(schedule)
            await db.commit()
            return

        # Check max auto-charge limit
        if total > user.max_auto_charge:
            await _notify_user(
                user,
                f"⚠️ *{schedule.name}* auto-order total ₹{total / 100:.2f} exceeds your "
                f"₹{user.max_auto_charge / 100:.0f} limit. Please confirm manually via /schedules.",
            )
            _reschedule(schedule)
            await db.commit()
            return

        try:
            swiggy_response = await client.place_order({
                "user_phone": user.phone,
                "items": cart_items,
                "address": user.address,
                "payment_method_id": user.payment_method_id,
            })

            order = Order(
                user_phone=user.phone,
                type=OrderType.GROCERY,
                swiggy_order_id=swiggy_response.get("order_id"),
                schedule_id=schedule.id,
                status=OrderStatus.PLACED,
                items=cart_items,
                subtotal=total,
                delivery_fee=2500,
                total=total + 2500,
            )
            db.add(order)
            _reschedule(schedule)
            await db.commit()

            await _notify_user(
                user,
                f"✅ *{schedule.name}* order placed!\n\n"
                f"{len(cart_items)} items — ₹{(total + 2500) / 100:.2f}\n"
                f"Next order: {schedule.next_run.strftime('%d %b %Y')}.",
            )
        except Exception:
            logger.exception("Swiggy order placement failed for schedule %s", schedule_id)
            await _notify_user(
                user,
                f"⚠️ Auto-order for *{schedule.name}* failed. Please check your items and try again via /schedules.",
            )
            _reschedule(schedule)
            await db.commit()


def _reschedule(schedule) -> None:
    from datetime import timedelta
    from src.models.schedule import FrequencyUnit

    now = datetime.now(timezone.utc)
    if schedule.freq_unit == FrequencyUnit.DAYS:
        schedule.next_run = now + timedelta(days=schedule.freq_value)
    elif schedule.freq_unit == FrequencyUnit.WEEKS:
        schedule.next_run = now + timedelta(weeks=schedule.freq_value)
    elif schedule.freq_unit == FrequencyUnit.MONTHS:
        from dateutil.relativedelta import relativedelta
        schedule.next_run = now + relativedelta(months=schedule.freq_value)


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
        logger.exception("Failed to notify user %s", user.phone)
