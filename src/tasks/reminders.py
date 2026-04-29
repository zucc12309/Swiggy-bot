import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_reminder(self, schedule_id: int) -> None:
    try:
        asyncio.get_event_loop().run_until_complete(_send_reminder(schedule_id))
    except Exception as exc:
        logger.exception("Reminder failed for schedule %s", schedule_id)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)


@celery_app.task
def check_due_reminders() -> None:
    asyncio.get_event_loop().run_until_complete(_check_due_reminders())


@celery_app.task
def send_weekly_summaries() -> None:
    asyncio.get_event_loop().run_until_complete(_send_weekly_summaries())


async def _check_due_reminders() -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus
    from src.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Schedule).where(
                Schedule.status == ScheduleStatus.ACTIVE,
                Schedule.reminder_enabled == 1,
            )
        )
        schedules = result.scalars().all()

        for sched in schedules:
            user_result = await db.execute(select(User).where(User.phone == sched.user_phone))
            user = user_result.scalar_one_or_none()
            if not user:
                continue

            lead_hours = user.reminder_lead_hours or 12
            reminder_time = sched.next_run - timedelta(hours=lead_hours)

            if reminder_time <= now < reminder_time + timedelta(minutes=15):
                send_reminder.delay(sched.id)
                logger.info("Queued reminder for schedule %s", sched.id)


async def _send_reminder(schedule_id: int) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus
    from src.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule or schedule.status != ScheduleStatus.ACTIVE:
            return

        user_result = await db.execute(select(User).where(User.phone == schedule.user_phone))
        user = user_result.scalar_one_or_none()
        if not user or not user.telegram_id:
            return

        items = schedule.items
        items_text = "\n".join(f"  • {i.name} × {i.quantity} {i.unit or 'pcs'}" for i in items)
        next_run_str = schedule.next_run.strftime("%d %b %Y at %I:%M %p IST")

        from src.adapters.base import Button, OutboundMessage
        from src.adapters.telegram import TelegramAdapter
        from telegram.ext import Application
        from config.settings import settings

        app = Application.builder().token(settings.telegram_bot_token).build()
        await app.initialize()
        adapter = TelegramAdapter(app)

        await adapter.send_buttons(
            user.telegram_id,
            f"⏰ *Reminder: {schedule.name}*\n\n"
            f"Your auto-restock order is scheduled for *{next_run_str}*.\n\n"
            f"Items:\n{items_text}\n\n"
            f"Tap OK to confirm, or choose another action:",
            [
                [Button("✅ OK — Place Order", f"remind_ok_{schedule.id}"),
                 Button("✏️ Edit Cart", f"remind_edit_{schedule.id}")],
                [Button("⏭ Skip This Run", f"remind_skip_{schedule.id}"),
                 Button("⏸ Pause Schedule", f"remind_pause_{schedule.id}")],
            ],
        )
        await app.shutdown()

    logger.info("Reminder sent for schedule %s (user %s)", schedule.name, schedule.user_phone)


async def _send_weekly_summaries() -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.order import Order, OrderType
    from src.models.user import User
    from sqlalchemy import select, func

    logger.info("Sending weekly spend summaries")
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    prev_week_start = week_ago - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        users_result = await db.execute(select(User).where(User.is_active == True))
        users = users_result.scalars().all()

        for user in users:
            if not user.telegram_id:
                continue

            orders_result = await db.execute(
                select(Order).where(
                    Order.user_phone == user.phone,
                    Order.created_at >= week_ago,
                    Order.status.in_(["delivered", "confirmed", "placed"]),
                )
            )
            orders = orders_result.scalars().all()
            if not orders:
                continue

            food_total = sum(o.total for o in orders if o.type == OrderType.FOOD)
            grocery_total = sum(o.total for o in orders if o.type == OrderType.GROCERY)
            total = food_total + grocery_total

            from src.adapters.base import OutboundMessage
            from src.adapters.telegram import TelegramAdapter
            from telegram.ext import Application
            from config.settings import settings

            app = Application.builder().token(settings.telegram_bot_token).build()
            await app.initialize()
            adapter = TelegramAdapter(app)

            await adapter.send_message(
                user.telegram_id,
                OutboundMessage(
                    text=f"📊 *Weekly Spend Summary*\n\n"
                         f"🍔 Food: ₹{food_total / 100:.2f}\n"
                         f"🛒 Groceries: ₹{grocery_total / 100:.2f}\n"
                         f"*Total: ₹{total / 100:.2f}* across {len(orders)} orders\n\n"
                         f"Type *show my spend* for more details.",
                ),
            )
            await app.shutdown()
