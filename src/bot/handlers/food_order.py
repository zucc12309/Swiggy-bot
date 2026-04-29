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
    lat, lng = float(sess.get("lat", 12.9716)), float(sess.get("lng", 77.5946))

    await adapter.send_message(user_id, OutboundMessage(text="🔍 Searching nearby restaurants..."))
    try:
        restaurants = await food_client.search_restaurants(query, lat, lng)
    except Exception:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ Couldn't reach Swiggy right now. Please try again in a moment."
        ))
        return

    if not restaurants:
        await adapter.send_message(user_id, OutboundMessage(
            text="😕 No restaurants found for that search. Try a different dish or cuisine."
        ))
        return

    await session.update(user_id, {"state": "FOOD_ORDER", "step": "select_restaurant",
                                   "restaurants": restaurants, "cart": []})
    buttons = [
        [Button(f"🍽 {r['name']} ({r.get('rating', '?')}⭐ · {r.get('eta', '?')} min)", f"rest_{r['id']}")]
        for r in restaurants[:3]
    ]
    await adapter.send_buttons(user_id, "Here are the top results:", buttons)


async def handle_restaurant_select(user_id: str, restaurant_id: str, adapter: MessagingAdapter,
                                   session: SessionService) -> None:
    await session.update(user_id, {"step": "select_category", "restaurant_id": restaurant_id, "cart": []})
    try:
        menu = await food_client.get_menu(restaurant_id)
    except Exception:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ Couldn't fetch the menu. Please try again."
        ))
        return

    categories = menu.get("categories", [])[:5]
    await session.update(user_id, {"menu_categories": categories})
    buttons = [[Button(c["name"], f"cat_{c['id']}")] for c in categories]
    buttons.append([Button("🛒 View Cart / Checkout", "checkout")])
    await adapter.send_buttons(user_id, "📋 Menu — choose a category:", buttons)


async def handle_category_select(user_id: str, category_id: str, adapter: MessagingAdapter,
                                 session: SessionService) -> None:
    sess = await session.get(user_id)
    categories = sess.get("menu_categories", [])
    category = next((c for c in categories if str(c["id"]) == category_id), None)
    if not category:
        return

    items = category.get("items", [])[:8]
    await session.update(user_id, {"current_category_items": items})
    buttons = [
        [Button(f"{i['name']} — ₹{i['price'] / 100:.0f}", f"item_{i['id']}")]
        for i in items
    ]
    buttons.append([Button("⬅️ Back to Menu", f"rest_{sess.get('restaurant_id')}")])
    await adapter.send_buttons(user_id, f"*{category['name']}* — tap to add:", buttons)


async def handle_item_add(user_id: str, item_id: str, adapter: MessagingAdapter,
                          session: SessionService) -> None:
    sess = await session.get(user_id)
    items = sess.get("current_category_items", [])
    item = next((i for i in items if str(i["id"]) == item_id), None)
    if not item:
        return

    cart = sess.get("cart", [])
    existing = next((c for c in cart if c["id"] == item["id"]), None)
    if existing:
        existing["qty"] += 1
    else:
        cart.append({"id": item["id"], "name": item["name"], "price": item["price"], "qty": 1})

    await session.update(user_id, {"cart": cart})
    await adapter.send_buttons(
        user_id,
        f"✅ Added *{item['name']}*. Cart has {sum(i['qty'] for i in cart)} item(s).",
        [
            [Button("➕ Add More", f"rest_{sess.get('restaurant_id')}"),
             Button("🛒 Checkout", "checkout")],
        ],
    )


async def handle_checkout(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    sess = await session.get(user_id)
    cart = sess.get("cart", [])
    if not cart:
        await adapter.send_message(user_id, OutboundMessage(
            text="Your cart is empty. Add some items first!"
        ))
        return

    lines = "\n".join(
        f"• {item['name']} ×{item['qty']} — ₹{item['price'] * item['qty'] / 100:.2f}"
        for item in cart
    )
    subtotal = sum(item["price"] * item["qty"] for item in cart)
    delivery = 3000  # ₹30 placeholder
    total = subtotal + delivery

    await session.update(user_id, {"state": "PAYMENT_PENDING", "order_type": "food", "total": total})
    await adapter.send_buttons(
        user_id,
        f"🛒 *Order Summary*\n\n{lines}\n\nSubtotal: ₹{subtotal / 100:.2f}\nDelivery: ₹{delivery / 100:.2f}\n*Total: ₹{total / 100:.2f}*",
        [
            [Button("✅ Confirm & Pay", "confirm_pay"), Button("✏️ Edit Cart", "edit_cart")],
            [Button("❌ Cancel", "cancel_order")],
        ],
    )


async def handle_edit_cart(user_id: str, adapter: MessagingAdapter, session: SessionService) -> None:
    sess = await session.get(user_id)
    cart = sess.get("cart", [])
    if not cart:
        await adapter.send_message(user_id, OutboundMessage(text="Cart is already empty."))
        return

    buttons = [
        [Button(f"❌ Remove {item['name']} ×{item['qty']}", f"remove_item_{item['id']}")]
        for item in cart
    ]
    buttons.append([Button("✅ Done Editing", "checkout")])
    await adapter.send_buttons(user_id, "Tap an item to remove it:", buttons)


async def handle_remove_item(user_id: str, item_id: str, adapter: MessagingAdapter,
                             session: SessionService) -> None:
    sess = await session.get(user_id)
    cart = [i for i in sess.get("cart", []) if str(i["id"]) != item_id]
    await session.update(user_id, {"cart": cart})
    if cart:
        await handle_edit_cart(user_id, adapter, session)
    else:
        await adapter.send_message(user_id, OutboundMessage(
            text="Cart is now empty. Type a dish name to search again."
        ))
        await session.update(user_id, {"state": "FOOD_ORDER", "step": "search"})
