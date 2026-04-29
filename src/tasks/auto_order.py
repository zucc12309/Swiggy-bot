import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def execute_auto_order(self, schedule_id: int) -> None:
    """Place a Swiggy Instamart order for a restock schedule."""
    try:
        asyncio.get_event_loop().run_until_complete(_execute_auto_order(schedule_id))
    except Exception as exc:
        logger.exception("Auto-order failed for schedule %s", schedule_id)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 300)


async def _execute_auto_order(schedule_id: int) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.schedule import Schedule, ScheduleStatus, FrequencyUnit
    from src.services.swiggy_instamart import SwiggyInstamartClient
    from sqlalchemy import select
    from dateutil.relativedelta import relativedelta

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = result.scalar_one_or_none()
        if not schedule or schedule.status != ScheduleStatus.ACTIVE:
            return

        # Recalculate next run
        now = datetime.now(timezone.utc)
        if schedule.freq_unit == FrequencyUnit.DAYS:
            schedule.next_run = now + timedelta(days=schedule.freq_value)
        elif schedule.freq_unit == FrequencyUnit.WEEKS:
            schedule.next_run = now + timedelta(weeks=schedule.freq_value)
        elif schedule.freq_unit == FrequencyUnit.MONTHS:
            schedule.next_run = now + relativedelta(months=schedule.freq_value)

        await db.commit()
        logger.info("Auto-order executed and rescheduled for schedule %s", schedule_id)
