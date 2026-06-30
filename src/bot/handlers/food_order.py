"""Food ordering using Swiggy Food MCP.

Enforces v1 constraints:
- COD only (Swiggy MCP doesn't accept online payment in v1)
- ₹1000 cart cap on Builders Club orders
- Cart is server-side; always get_food_cart before mutating or confirming
- Cart binds to one restaurant; switching restaurant auto-flushes
- place_food_order is non-idempotent — on failure, check get_food_orders first
"""
import logging

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService
from src.services.swiggy_food import SwiggyFoodClient, FOOD_CART_CAP_PAISE
from src.services.swiggy_mcp import SwiggyMCPError

logger = logging.getLogger(__name__)
food_client = SwiggyFoodClient()


async def _require_token_and_address(user_id: str, adapter: MessagingAdapter):
    from src.db.database import AsyncSessionLocal
    from src.models.user import User
    from src.services import swiggy_auth
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.swiggy_access_token:
            await adapter.send_message(user_id, OutboundMessage(
                text="🔗 Please /start to connect your Swiggy account first."
            ))
            return None, None
        if swiggy_auth.is_token_expired(user.swiggy_token_expires_at):
            await adapter.send_message(user_id, OutboundMessage(
                text="🔗 Your Swiggy session expired. Type /start to reconnect."
            ))
            return None, None
        if not user.swiggy_selected_address_id:
            await adapter.send_message(user_id, OutboundMessage(
                text="📍 Please pick a delivery address — type /start to reconnect."
            ))
            return None, None
        return user.swiggy_access_token, user.swiggy_selected_address_id


async def handle_food_search(user_id: str, query: str, adapter: MessagingAdapter,
                             session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    await adapter.send_message(user_id, OutboundMessage(text="🔍 Searching restaurants..."))
    try:
        result = await food_client.search_restaurants(token, address_id, query)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"⚠️ {e.message}" if not e.is_auth else "🔗 Session expired. /start to reconnect."
        ))
        return

    restaurants = result.get("restaurants", []) if isinstance(result, dict) else []
    open_ones = [r for r in restaurants if r.get("availabilityStatus") == "OPEN"][:3]
    if not open_ones:
        await adapter.send_message(user_id, OutboundMessage(
            text="😕 No open restaurants found. Try a different search."
        ))
        return

    await session.update(user_id, {
        "state": "FOOD_ORDER", "step": "select_restaurant",
        "restaurants": open_ones, "address_id": address_id,
    })

    buttons = []
    for r in open_ones:
        rating = r.get("rating") or r.get("avgRating") or "?"
        dist = r.get("distanceKm")
        dist_str = f" · {dist}km" if dist else ""
        buttons.append([Button(f"🍽 {r['name'][:30]} ({rating}⭐{dist_str})", f"rest_{r['id']}")])

    await adapter.send_buttons(user_id, "Pick a restaurant:", buttons)


async def handle_restaurant_select(user_id: str, restaurant_id: str,
                                   adapter: MessagingAdapter, session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    sess = await session.get(user_id)
    restaurant = next((r for r in (sess or {}).get("restaurants", [])
                       if str(r.get("id")) == restaurant_id), None)
    restaurant_name = restaurant.get("name") if restaurant else None

    await session.update(user_id, {
        "step": "select_items", "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
    })

    await adapter.send_message(user_id, OutboundMessage(
        text=f"📋 *{restaurant_name or 'Menu'}*\n\nWhat would you like? "
             f"(e.g. *biryani*, *paneer tikka*) — or type *cart* to see your cart."
    ))


async def handle_dish_search(user_id: str, query: str, adapter: MessagingAdapter,
                             session: SessionService) -> None:
    """User typed a dish name during food ordering — search_menu within restaurant."""
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    sess = await session.get(user_id)
    restaurant_id = (sess or {}).get("restaurant_id")
    if not restaurant_id:
        await handle_food_search(user_id, query, adapter, session)
        return

    try:
        result = await food_client.search_menu(token, address_id, query,
                                               restaurant_id=restaurant_id)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))
        return

    items = result.get("items", [])[:6] if isinstance(result, dict) else []
    if not items:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"😕 No dishes matched *{query}* here."
        ))
        return

    await session.update(user_id, {"search_results": items})
    buttons = []
    for it in items:
        price_rs = _price_rupees(it.get("price", 0))
        buttons.append([Button(f"{it['name'][:30]} — ₹{price_rs:.0f}", f"additem_{it['id']}")])
    buttons.append([Button("🛒 Checkout", "checkout")])
    await adapter.send_buttons(user_id, "Tap to add:", buttons)


async def handle_item_add(user_id: str, item_id: str, adapter: MessagingAdapter,
                          session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    sess = await session.get(user_id)
    item = next((i for i in (sess or {}).get("search_results", [])
                 if str(i.get("id")) == item_id), None)
    if not item:
        return

    restaurant_id = (sess or {}).get("restaurant_id")
    restaurant_name = (sess or {}).get("restaurant_name")

    cart_entry = {"itemId": item["id"], "quantity": 1}
    if item.get("variantsV2"):
        cart_entry["variantsV2"] = []
    elif item.get("variations"):
        cart_entry["variations"] = []

    try:
        await food_client.update_food_cart(token, address_id, restaurant_id,
                                           [cart_entry], restaurant_name)
        cart = await food_client.get_food_cart(token, address_id, restaurant_name)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))
        return

    total = _cart_total(cart)
    await adapter.send_buttons(
        user_id,
        f"✅ Added *{item['name']}*. Cart total: ₹{total / 100:.2f}",
        [[Button("➕ Add More", "add_more"), Button("🛒 Checkout", "checkout")]],
    )


async def handle_checkout(user_id: str, adapter: MessagingAdapter,
                          session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    sess = await session.get(user_id)
    restaurant_name = (sess or {}).get("restaurant_name")

    try:
        cart = await food_client.get_food_cart(token, address_id, restaurant_name)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))
        return

    total = _cart_total(cart)
    if total == 0:
        await adapter.send_message(user_id, OutboundMessage(text="Your cart is empty."))
        return

    if total >= FOOD_CART_CAP_PAISE:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"⚠️ Cart total ₹{total / 100:.2f} exceeds Swiggy's *₹1000 limit* on bot orders. "
                 f"Reduce items, or place this order in the Swiggy app."
        ))
        return

    items_summary = _cart_summary(cart)
    payment_methods = cart.get("availablePaymentMethods", []) if isinstance(cart, dict) else []
    payment_str = payment_methods[0] if payment_methods else "COD"

    await session.update(user_id, {"state": "PAYMENT_PENDING", "order_type": "food",
                                   "total": total, "payment_method": payment_str})
    await adapter.send_buttons(
        user_id,
        f"🛒 *Order Summary*\n\n{items_summary}\n\n"
        f"*Total: ₹{total / 100:.2f}*\n"
        f"Payment: {payment_str}\n"
        f"Delivery: your saved address",
        [
            [Button("✅ Place Order", "confirm_pay"), Button("❌ Cancel", "cancel_order")],
            [Button("🗑 Empty Cart", "flush_cart")],
        ],
    )


async def handle_flush_cart(user_id: str, adapter: MessagingAdapter,
                            session: SessionService) -> None:
    token, _ = await _require_token_and_address(user_id, adapter)
    if not token:
        return
    try:
        await food_client.flush_food_cart(token)
        await adapter.send_message(user_id, OutboundMessage(text="🗑 Cart emptied."))
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))


def _price_rupees(price) -> float:
    """Normalise a price field that may be paise or rupees."""
    if not price:
        return 0
    return price / 100 if price > 1000 else price


def _cart_total(cart) -> int:
    """Return cart total in paise. Best-effort across response shapes."""
    if not isinstance(cart, dict):
        return 0
    for key in ("total", "grandTotal", "billTotal"):
        v = cart.get(key)
        if isinstance(v, (int, float)):
            return int(v) if v > 1000 else int(v * 100)
    total = 0
    for it in cart.get("items", []):
        price = it.get("price", 0) or it.get("totalPrice", 0)
        qty = it.get("quantity", 1)
        total += int(price * qty * (1 if price > 1000 else 100))
    return total


def _cart_summary(cart) -> str:
    if not isinstance(cart, dict):
        return ""
    items = cart.get("items", [])
    if not items:
        return "(empty)"
    lines = []
    for it in items[:10]:
        price = it.get("price", 0)
        qty = it.get("quantity", 1)
        line_paise = price * qty if price > 1000 else price * qty * 100
        lines.append(f"• {it.get('name', 'item')} ×{qty} — ₹{line_paise / 100:.2f}")
    return "\n".join(lines)
