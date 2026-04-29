import logging
from typing import Any, Dict

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService
from src.services.swiggy_instamart import SwiggyInstamartClient

logger = logging.getLogger(__name__)
instamart_client = SwiggyInstamartClient()

UNIT_OPTIONS = [
    [Button("1 pc", "unit_1_pcs"), Button("2 pcs", "unit_2_pcs"), Button("500 g", "unit_500_g")],
    [Button("1 kg", "unit_1_kg"), Button("2 kg", "unit_2_kg"), Button("1 litre", "unit_1_litre")],
    [Button("🛒 View Cart", "grocery_checkout")],
]


async def handle_grocery_start(user_id: str, query: str, adapter: MessagingAdapter,
                               session: SessionService) -> None:
    await session.update(user_id, {"state": "GROCERY_ORDER", "step": "search", "grocery_cart": []})
    await _search_products(user_id, query, adapter, session)


async def handle_grocery_message(user_id: str, text: str, adapter: MessagingAdapter,
                                 session: SessionService) -> None:
    sess = await session.get(user_id)
    step = sess.get("step") if sess else "search"
    cb = None
    if text.startswith("unit_"):
        cb = text

    if cb and cb.startswith("unit_"):
        await _handle_unit_select(user_id, cb, adapter, session)
    elif cb == "grocery_checkout":
        await handle_grocery_checkout(user_id, adapter, session)
    elif text.lower() == "done" or text.lower() == "checkout":
        await handle_grocery_checkout(user_id, adapter, session)
    else:
        await _search_products(user_id, text, adapter, session)


async def handle_grocery_callback(user_id: str, callback_data: str, adapter: MessagingAdapter,
                                  session: SessionService) -> None:
    if callback_data.startswith("prod_"):
        await _handle_product_select(user_id, callback_data[5:], adapter, session)
    elif callback_data.startswith("unit_"):
        await _handle_unit_select(user_id, callback_data, adapter, session)
    elif callback_data == "grocery_checkout":
        await handle_grocery_checkout(user_id, adapter, session)
    elif callback_data == "grocery_more":
        await adapter.send_message(user_id, OutboundMessage(
            text="What else would you like to add? Search for another item or type *done* to checkout."
        ))


async def _search_products(user_id: str, query: str, adapter: MessagingAdapter,
                           session: SessionService) -> None:
    sess = await session.get(user_id)
    lat, lng = float(sess.get("lat", 12.9716)), float(sess.get("lng", 77.5946))

    await adapter.send_message(user_id, OutboundMessage(text=f"🔍 Searching for *{query}*..."))
    try:
        products = await instamart_client.search_products(query, lat, lng)
    except Exception:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ Couldn't reach Instamart right now. Please try again in a moment."
        ))
        return

    if not products:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"😕 No results for *{query}*. Try a different name or brand."
        ))
        return

    await session.update(user_id, {"grocery_products": products[:5]})
    buttons = [
        [Button(f"{p['name']} — ₹{p['price'] / 100:.0f}/{p.get('unit', 'pc')}", f"prod_{p['id']}")]
        for p in products[:5]
    ]
    buttons.append([Button("🛒 Checkout", "grocery_checkout")])
    await adapter.send_buttons(user_id, "Select a product:", buttons)


async def _handle_product_select(user_id: str, product_id: str, adapter: MessagingAdapter,
                                 session: SessionService) -> None:
    sess = await session.get(user_id)
    products = sess.get("grocery_products", [])
    product = next((p for p in products if str(p["id"]) == product_id), None)
    if not product:
        await adapter.send_message(user_id, OutboundMessage(text="Product not found. Please search again."))
        return

    await session.update(user_id, {"pending_product": product})
    buttons = [
        [Button("1 pc", "unit_1_pcs"), Button("2 pcs", "unit_2_pcs"), Button("500 g", "unit_500_g")],
        [Button("1 kg", "unit_1_kg"), Button("2 kg", "unit_2_kg"), Button("1 L", "unit_1_litre")],
    ]
    await adapter.send_buttons(
        user_id,
        f"📦 *{product['name']}* — ₹{product['price'] / 100:.0f}\n\nSelect quantity:",
        buttons,
    )


async def _handle_unit_select(user_id: str, callback: str, adapter: MessagingAdapter,
                              session: SessionService) -> None:
    # callback format: unit_{qty}_{unit}  e.g. unit_1_kg, unit_500_g
    parts = callback.split("_", 2)
    qty = int(parts[1]) if len(parts) > 1 else 1
    unit = parts[2] if len(parts) > 2 else "pcs"

    sess = await session.get(user_id)
    product = sess.get("pending_product")
    if not product:
        return

    cart = sess.get("grocery_cart", [])
    existing = next((i for i in cart if i["id"] == product["id"]), None)
    if existing:
        existing["qty"] = qty
        existing["unit"] = unit
    else:
        cart.append({"id": product["id"], "name": product["name"],
                     "price": product["price"], "qty": qty, "unit": unit})

    await session.update(user_id, {"grocery_cart": cart, "pending_product": None})
    await adapter.send_buttons(
        user_id,
        f"✅ Added *{qty} {unit} of {product['name']}* to cart.\n\nAdd more items or checkout:",
        [
            [Button("🔍 Add More Items", "grocery_more")],
            [Button("🛒 Checkout", "grocery_checkout")],
        ],
    )


async def handle_grocery_checkout(user_id: str, adapter: MessagingAdapter,
                                  session: SessionService) -> None:
    sess = await session.get(user_id)
    cart = sess.get("grocery_cart", [])
    if not cart:
        await adapter.send_message(user_id, OutboundMessage(
            text="Your cart is empty. Search for items to add — e.g. *milk*, *tomatoes*, *rice*."
        ))
        return

    lines = "\n".join(
        f"• {item['name']} × {item['qty']} {item['unit']} — ₹{item['price'] * item['qty'] / 100:.2f}"
        for item in cart
    )
    subtotal = sum(item["price"] * item["qty"] for item in cart)
    delivery = 2500  # ₹25 placeholder
    total = subtotal + delivery

    await session.update(user_id, {"state": "PAYMENT_PENDING", "order_type": "grocery", "total": total})
    await adapter.send_buttons(
        user_id,
        f"🛒 *Grocery Cart*\n\n{lines}\n\nSubtotal: ₹{subtotal / 100:.2f}\nDelivery: ₹{delivery / 100:.2f}\n*Total: ₹{total / 100:.2f}*\n\n⏱ Estimated delivery: 15–30 mins",
        [
            [Button("✅ Confirm & Pay", "confirm_pay"), Button("✏️ Edit Cart", "edit_grocery_cart")],
            [Button("❌ Cancel", "cancel_order")],
        ],
    )
