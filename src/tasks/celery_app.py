from celery import Celery
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
)
