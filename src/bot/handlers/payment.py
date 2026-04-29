import logging
import uuid

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.payment import PaymentService
from src.services.session import SessionService

logger = logging.getLogger(__name__)
payment_service = PaymentService()


async def handle_confirm_pay(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    sess = await session.get(user_id)
    total = sess.get("total", 0)
    order_type = sess.get("order_type", "food")
    idempotency_key = str(uuid.uuid4())

    await session.update(user_id, {"idempotency_key": idempotency_key})

    try:
        link = payment_service.create_payment_link(
            amount=total,
            description=f"Swiggy {'Food' if order_type == 'food' else 'Instamart'} Order",
            order_id=idempotency_key,
            callback_url=f"https://your-domain.com/payment/callback/{user_id}",
        )
        await adapter.send_payment_link(
            user_id,
            url=link["short_url"],
            amount=total,
            description=f"Swiggy {'Food' if order_type == 'food' else 'Instamart'} Order",
        )
        await adapter.send_message(user_id, OutboundMessage(
            text="⏳ Waiting for payment confirmation. Your order will be placed automatically once payment is received."
        ))
    except Exception:
        logger.exception("Payment link creation failed for user %s", user_id)
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ Couldn't create payment link. Please try again or type /cancel to exit."
        ))
