import asyncio
import logging

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def poll_price_alerts() -> None:
    """Poll Instamart prices for all active alerts every 6 hours."""
    asyncio.get_event_loop().run_until_complete(_poll_price_alerts())


async def _poll_price_alerts() -> None:
    from src.services.swiggy_instamart import SwiggyInstamartClient

    client = SwiggyInstamartClient()
    logger.info("Price alert polling run started")
    # Batch all user alerts by product_id to minimise API calls
    # Implementation wired up once price_alerts table is added via migration
