"""Order placement handler — COD only in v1.

Swiggy MCP doesn't accept online payment in v1.0, so place_food_order /
checkout always run with Cash on Delivery. No Razorpay flow involved.

Order placement is non-idempotent: on 5xx we don't blind-retry. We check
get_food_orders / get_orders first to see if it actually went through.
"""
import asyncio
import logging
from typing import Optional

from src.adapters.base import MessagingAdapter, OutboundMessage
from src.models.order import Order, OrderStatus, OrderType
from src.services.session import SessionService
from src.services.swiggy_food import SwiggyFoodClient
from src.services.swiggy_instamart import SwiggyInstamartClient
from src.services.swiggy_mcp import SwiggyMCPError

logger = logging.getLogger(__name__)
food_client = SwiggyFoodClient()
instamart_client = SwiggyInstamartClient()


async def handle_confirm_pay(user_id: str, adapter: MessagingAdapter,
                             session: SessionService) -> None:
    """Place the order via Swiggy MCP. COD payment."""
    from src.db.database import AsyncSessionLocal
    from src.models.user import User
    from sqlalchemy import select

    sess = await session.get(user_id)
    order_type = (sess or {}).get("order_type", "food")
    payment_method = (sess or {}).get("payment_method", "COD")
    total = (sess or {}).get("total", 0)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.swiggy_access_token:
            await adapter.send_message(user_id, OutboundMessage(
                text="🔗 Please /start to reconnect Swiggy."
            ))
            return

        token = user.swiggy_access_token
        address_id = user.swiggy_selected_address_id

        await adapter.send_message(user_id, OutboundMessage(
            text="⏳ Placing your order..."
        ))

        try:
            if order_type == "food":
                resp = await food_client.place_food_order(token, address_id, payment_method)
            else:
                resp = await instamart_client.checkout(token, address_id, payment_method)
            order_id = _extract_order_id(resp)
        except SwiggyMCPError as e:
            await _handle_placement_failure(user_id, order_type, token, address_id,
                                            user.swiggy_selected_lat,
                                            user.swiggy_selected_lng,
                                            e, adapter)
            return

        # Persist locally
        order = Order(
            telegram_id=user_id,
            type=OrderType.FOOD if order_type == "food" else OrderType.GROCERY,
            swiggy_order_id=order_id,
            status=OrderStatus.PLACED,
            items=(sess or {}).get("cart_items_snapshot", []),
            subtotal=total,
            delivery_fee=0,
            total=total,
            restaurant_id=(sess or {}).get("restaurant_id"),
            restaurant_name=(sess or {}).get("restaurant_name"),
            payment_method=payment_method,
        )
        db.add(order)
        await db.commit()

    await session.update(user_id, {"state": "IDLE"})

    msg = _extract_response_message(resp) or "✅ Order placed!"
    await adapter.send_message(user_id, OutboundMessage(
        text=f"{msg}\n\nPay {payment_method} on delivery. Type *track* or /orders to see status."
    ))


async def _handle_placement_failure(user_id: str, order_type: str, token: str,
                                    address_id: str, lat: Optional[str], lng: Optional[str],
                                    error: SwiggyMCPError, adapter: MessagingAdapter) -> None:
    """Non-idempotent recovery: wait briefly, check if order placed anyway."""
    if not error.is_retryable:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"⚠️ Order failed: {error.message}\n\nNothing was charged. Type /menu to try again."
        ))
        return

    await asyncio.sleep(3)
    try:
        if order_type == "food":
            orders = await food_client.get_food_orders(token, address_id, order_count=1)
            recent = (orders.get("orders") or [None])[0] if isinstance(orders, dict) else None
        else:
            orders = await instamart_client.get_orders(token, count=1, active_only=True)
            recent = (orders.get("orders") or [None])[0] if isinstance(orders, dict) else None

        if recent:
            await adapter.send_message(user_id, OutboundMessage(
                text="✅ Looks like your order did go through despite the error! "
                     "Type /orders to see status."
            ))
            return
    except Exception:
        logger.exception("post-failure check failed")

    await adapter.send_message(user_id, OutboundMessage(
        text=f"⚠️ Order may not have been placed: {error.message}\n\n"
             f"Please type /orders to check, or try again."
    ))


def _extract_order_id(response) -> Optional[str]:
    if not isinstance(response, dict):
        return None
    for key in ("orderId", "order_id", "id"):
        v = response.get(key)
        if v:
            return str(v)
    return None


def _extract_response_message(response) -> Optional[str]:
    if not isinstance(response, dict):
        return None
    return response.get("message") or (response.get("data") or {}).get("message")
