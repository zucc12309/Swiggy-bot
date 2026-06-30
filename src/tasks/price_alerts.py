"""Price drop alerts — poll Instamart every 6h via search_products.

Note: Instamart has no batch product-lookup tool in v1. We re-search per
unique product_name per address. Keep alert counts modest.
"""
import asyncio
import logging
from collections import defaultdict

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
    from src.services import swiggy_auth
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

        # Group by (telegram_id, address_id) so we batch search calls per user
        grouped = defaultdict(list)
        for a in alerts:
            grouped[(a.telegram_id, a.address_id)].append(a)

        for (telegram_id, address_id), bucket in grouped.items():
            user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_res.scalar_one_or_none()
            if not user or not user.swiggy_access_token:
                continue
            if swiggy_auth.is_token_expired(user.swiggy_token_expires_at):
                continue

            for alert in bucket:
                try:
                    res = await client.search_products(user.swiggy_access_token,
                                                       address_id, alert.product_name)
                except Exception:
                    logger.exception("search_products failed for alert %s", alert.id)
                    continue

                products = res.get("products", []) if isinstance(res, dict) else []
                current_price = None
                for p in products:
                    for v in (p.get("variants") or []):
                        if v.get("spinId") == alert.product_spin_id:
                            current_price = v.get("price")
                            break
                    if current_price is not None:
                        break

                if current_price is None:
                    continue
                if current_price <= alert.target_price:
                    await _fire_alert(alert, current_price, user)

        await db.commit()


async def _fire_alert(alert, current_price: int, user) -> None:
    from src.models.price_alert import PriceAlertStatus
    from src.adapters.base import Button, OutboundMessage

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
            [[Button("🛒 Order Now", f"prod_{alert.product_spin_id}"),
              Button("⏰ Remind Later", f"snooze_alert_{alert.id}")]],
        )
        await app.shutdown()
        logger.info("Price alert fired for %s (user %s)",
                    alert.product_name, alert.telegram_id)
    except Exception:
        logger.exception("Failed to send price alert for %s", alert.product_spin_id)
