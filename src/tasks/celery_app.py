from celery import Celery
from celery.schedules import crontab

from config.settings import settings

celery_app = Celery(
    "swiggy_bot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "src.tasks.reminders",
        "src.tasks.auto_order",
        "src.tasks.price_alerts",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_max_retries=3,
    beat_schedule={
        # Check for schedules needing reminders every 15 minutes
        "check-schedule-reminders": {
            "task": "src.tasks.reminders.check_due_reminders",
            "schedule": crontab(minute="*/15"),
        },
        # Check for auto-orders due to execute every 5 minutes
        "check-auto-orders": {
            "task": "src.tasks.auto_order.check_due_orders",
            "schedule": crontab(minute="*/5"),
        },
        # Poll price alerts every 6 hours
        "poll-price-alerts": {
            "task": "src.tasks.price_alerts.poll_price_alerts",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        # Weekly spend summary every Monday at 9am IST
        "weekly-spend-summary": {
            "task": "src.tasks.reminders.send_weekly_summaries",
            "schedule": crontab(minute=0, hour=9, day_of_week="monday"),
        },
    },
)
