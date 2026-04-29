import logging
from typing import Any, Dict

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService
from src.services.swiggy_food import SwiggyFoodClient

logger = logging.getLogger(__name__)
food_client = SwiggyFoodClient()


async def handle_food_search(user_id: str, query: str, adapter: MessagingAdapter,
                             session: SessionService) -> None:
    sess = await session.get(user_id)
    lat, lng = float(sess["lat"]), float(sess["lng"])

    await adapter.send_message(user_id, OutboundMessage(text="🔍 Searching nearby restaurants..."))
    restaurants = await food_client.search_restaurants(query, lat, lng)

    if not restaurants:
        await adapter.send_message(user_id, OutboundMessage(text="😕 No restaurants found for that search. Try a different dish or cuisine."))
        return

    await session.update(user_id, {"state": "FOOD_ORDER", "step": "select_restaurant", "restaurants": restaurants})
    buttons = [[Button(f"🍽 {r['name']} ({r['rating']}⭐ • {r['eta']} min)", f"rest_{r['id']}")] for r in restaurants[:3]]
    await adapter.send_buttons(user_id, "Here are the top results:", buttons)


async def handle_restaurant_select(user_id: str, restaurant_id: str, adapter: MessagingAdapter,
                                   session: SessionService) -> None:
    await session.update(user_id, {"step": "select_items", "restaurant_id": restaurant_id, "cart": []})
    menu = await food_client.get_menu(restaurant_id)

    categories = menu.get("categories", [])[:4]
    buttons = [[Button(c["name"], f"cat_{c['id']}")] for c in categories]
    buttons.append([Button("🛒 View Cart / Checkout", "checkout")])
    await adapter.send_buttons(user_id, f"📋 Menu — choose a category:", buttons)


async def handle_checkout(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    sess = await session.get(user_id)
    cart = sess.get("cart", [])
    if not cart:
        await adapter.send_message(user_id, OutboundMessage(text="Your cart is empty. Add some items first!"))
        return

    lines = "\n".join(f"• {item['name']} x{item['qty']} — ₹{item['price'] * item['qty'] / 100:.2f}" for item in cart)
    total = sum(item["price"] * item["qty"] for item in cart)
    delivery = 3000  # ₹30 placeholder
    text = f"🛒 *Order Summary*\n\n{lines}\n\nSubtotal: ₹{total / 100:.2f}\nDelivery: ₹{delivery / 100:.2f}\n*Total: ₹{(total + delivery) / 100:.2f}*"

    await session.update(user_id, {"state": "PAYMENT_PENDING", "total": total + delivery})
    await adapter.send_buttons(user_id, text, [
        [Button("✅ Confirm & Pay", "confirm_pay"), Button("✏️ Edit Cart", "edit_cart")],
    ])
