import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_reminder(self, schedule_id: int) -> None:
    """Fire a pre-order reminder for a restock schedule."""
    try:
        asyncio.get_event_loop().run_until_complete(_send_reminder(schedule_id))
    except Exception as exc:
        logger.exception("Reminder failed for schedule %s", schedule_id)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)


async def _send_reminder(schedule_id: int) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule
    from src.services.session import SessionService
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule or schedule.status != "active":
            return

        logger.info("Reminder sent for schedule %s (user %s)", schedule.name, schedule.user_phone)
