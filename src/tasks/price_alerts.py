import asyncio
import logging

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def poll_price_alerts() -> None:
    asyncio.get_event_loop().run_until_complete(_poll_price_alerts())


async def _poll_price_alerts() -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.price_alert import PriceAlert, PriceAlertStatus
    from src.models.user import User
    from src.services.swiggy_instamart import SwiggyInstamartClient
    from sqlalchemy import select

    client = SwiggyInstamartClient()
    logger.info("Price alert polling started")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PriceAlert).where(PriceAlert.status == PriceAlertStatus.ACTIVE)
        )
        alerts = result.scalars().all()
        if not alerts:
            return

        # Batch by product_id to minimise API calls
        product_ids = list({a.product_id for a in alerts})
        try:
            products = await client.get_products_batch(product_ids)
        except Exception:
            logger.exception("Instamart batch fetch failed during price alert poll")
            return

        price_map = {p["id"]: p["price"] for p in products}

        for alert in alerts:
            current_price = price_map.get(alert.product_id)
            if current_price is None:
                continue
            if current_price <= alert.target_price:
                await _fire_alert(alert, current_price, db)

        await db.commit()


async def _fire_alert(alert, current_price: int, db) -> None:
    from src.models.price_alert import PriceAlertStatus
    from src.models.user import User
    from src.adapters.base import Button, OutboundMessage
    from sqlalchemy import select

    user_result = await db.execute(select(User).where(User.phone == alert.user_phone))
    user = user_result.scalar_one_or_none()
    if not user or not user.telegram_id:
        return

    savings = alert.previous_price - current_price
    alert.status = PriceAlertStatus.FIRED

    try:
        from src.adapters.telegram import TelegramAdapter
        from telegram.ext import Application
        from config.settings import settings

        app = Application.builder().token(settings.telegram_bot_token).build()
        await app.initialize()
        adapter = TelegramAdapter(app)

        await adapter.send_buttons(
            user.telegram_id,
            f"🔔 *Price Drop Alert!*\n\n"
            f"*{alert.product_name}* dropped to ₹{current_price / 100:.2f}\n"
            f"Was: ₹{alert.previous_price / 100:.2f} — You save ₹{savings / 100:.2f}!",
            [
                [Button("🛒 Order Now", f"prod_{alert.product_id}"),
                 Button("⏰ Remind Later", f"snooze_alert_{alert.id}")],
            ],
        )
        await app.shutdown()
        logger.info("Price alert fired for %s (user %s)", alert.product_name, alert.user_phone)
    except Exception:
        logger.exception("Failed to send price alert for %s", alert.product_id)
