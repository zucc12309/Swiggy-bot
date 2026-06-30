"""Grocery ordering using Swiggy Instamart MCP.

v1 constraints:
- COD only
- Cart bound to delivery address — clear_cart before any address switch
- Server-side cart — get_cart before mutations and checkout
- checkout is non-idempotent — on 5xx, check get_orders before retrying
"""
import logging

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService
from src.services.swiggy_instamart import SwiggyInstamartClient
from src.services.swiggy_mcp import SwiggyMCPError

logger = logging.getLogger(__name__)
instamart_client = SwiggyInstamartClient()


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


async def handle_grocery_start(user_id: str, query: str, adapter: MessagingAdapter,
                               session: SessionService) -> None:
    await session.update(user_id, {"state": "GROCERY_ORDER", "step": "search"})
    if query and query not in ("order groceries", "groceries", "grocery", "instamart"):
        await _search_products(user_id, query, adapter, session)
    else:
        await _offer_go_to_or_search(user_id, adapter, session)


async def _offer_go_to_or_search(user_id: str, adapter: MessagingAdapter,
                                 session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return
    try:
        go_to = await instamart_client.your_go_to_items(token, address_id)
        items = go_to.get("products", [])[:5] if isinstance(go_to, dict) else []
    except SwiggyMCPError:
        items = []

    if items:
        await session.update(user_id, {"go_to_items": items})
        buttons = [[Button(f"🔁 {p['name'][:30]}", f"goto_{i}")] for i, p in enumerate(items)]
        buttons.append([Button("🔍 Search Something Else", "grocery_search_more")])
        await adapter.send_buttons(
            user_id,
            "🛒 Your usual items — tap to add, or search for something new:",
            buttons,
        )
    else:
        await adapter.send_message(user_id, OutboundMessage(
            text="🛒 What would you like? (e.g. *milk*, *tomatoes*, *rice*)"
        ))


async def handle_grocery_message(user_id: str, text: str, adapter: MessagingAdapter,
                                 session: SessionService) -> None:
    text_lower = text.lower().strip()
    if text_lower in ("done", "checkout", "cart"):
        await handle_grocery_checkout(user_id, adapter, session)
    else:
        await _search_products(user_id, text, adapter, session)


async def handle_grocery_callback(user_id: str, callback_data: str,
                                  adapter: MessagingAdapter, session: SessionService) -> None:
    if callback_data.startswith("prod_"):
        await _handle_product_select(user_id, callback_data[5:], adapter, session)
    elif callback_data.startswith("variant_"):
        await _handle_variant_add(user_id, callback_data[8:], adapter, session)
    elif callback_data.startswith("goto_"):
        await _handle_goto_add(user_id, int(callback_data[5:]), adapter, session)
    elif callback_data == "grocery_search_more":
        await adapter.send_message(user_id, OutboundMessage(
            text="🔍 What would you like to search for?"
        ))
    elif callback_data == "grocery_checkout":
        await handle_grocery_checkout(user_id, adapter, session)
    elif callback_data == "grocery_clear":
        await _clear_cart(user_id, adapter, session)


async def _search_products(user_id: str, query: str, adapter: MessagingAdapter,
                           session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    await adapter.send_message(user_id, OutboundMessage(text=f"🔍 Searching for *{query}*..."))
    try:
        result = await instamart_client.search_products(token, address_id, query)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))
        return

    products = result.get("products", [])[:5] if isinstance(result, dict) else []
    if not products:
        await adapter.send_message(user_id, OutboundMessage(
            text=f"😕 No results for *{query}*. Try a different name."
        ))
        return

    await session.update(user_id, {"products": products})
    buttons = []
    for i, p in enumerate(products):
        variants = p.get("variants") or []
        price_rs = _price_rupees(variants[0]["price"]) if variants else 0
        buttons.append([Button(f"{p['name'][:30]} — ₹{price_rs:.0f}", f"prod_{i}")])
    buttons.append([Button("🛒 Cart", "grocery_checkout")])
    await adapter.send_buttons(user_id, "Pick a product:", buttons)


async def _handle_product_select(user_id: str, idx_str: str, adapter: MessagingAdapter,
                                 session: SessionService) -> None:
    sess = await session.get(user_id)
    products = (sess or {}).get("products", [])
    try:
        product = products[int(idx_str)]
    except (ValueError, IndexError):
        return

    variants = product.get("variants") or []
    if not variants:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ This product has no available variants right now."
        ))
        return

    if len(variants) == 1:
        await _add_to_cart(user_id, variants[0], product["name"], adapter, session)
        return

    await session.update(user_id, {"current_variants": variants, "current_product": product})
    buttons = []
    for i, v in enumerate(variants[:5]):
        size = v.get("unit") or v.get("packSize") or v.get("quantity") or "1 pc"
        price_rs = _price_rupees(v.get("price", 0))
        buttons.append([Button(f"{size} — ₹{price_rs:.0f}", f"variant_{i}")])
    await adapter.send_buttons(
        user_id, f"📦 *{product['name']}* — pick a size:", buttons,
    )


async def _handle_variant_add(user_id: str, idx_str: str, adapter: MessagingAdapter,
                              session: SessionService) -> None:
    sess = await session.get(user_id)
    variants = (sess or {}).get("current_variants", [])
    product = (sess or {}).get("current_product", {})
    try:
        variant = variants[int(idx_str)]
    except (ValueError, IndexError):
        return
    await _add_to_cart(user_id, variant, product.get("name", "item"), adapter, session)


async def _handle_goto_add(user_id: str, idx: int, adapter: MessagingAdapter,
                           session: SessionService) -> None:
    sess = await session.get(user_id)
    items = (sess or {}).get("go_to_items", [])
    if idx >= len(items):
        return
    product = items[idx]
    variants = product.get("variants") or []
    if not variants:
        return
    await _add_to_cart(user_id, variants[0], product["name"], adapter, session)


async def _add_to_cart(user_id: str, variant, name: str, adapter: MessagingAdapter,
                       session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return
    spin_id = variant.get("spinId")
    if not spin_id:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ Couldn't add that variant — missing identifier."
        ))
        return

    try:
        # Read existing cart and add to it (update_cart REPLACES the cart, per docs)
        existing = await instamart_client.get_cart(token)
        cart_items = []
        if isinstance(existing, dict):
            for it in existing.get("items", []):
                if it.get("spinId"):
                    cart_items.append({"spinId": it["spinId"], "quantity": it.get("quantity", 1)})
        # add/increment the new item
        found = False
        for ci in cart_items:
            if ci["spinId"] == spin_id:
                ci["quantity"] += 1
                found = True
                break
        if not found:
            cart_items.append({"spinId": spin_id, "quantity": 1})

        await instamart_client.update_cart(token, address_id, cart_items)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))
        return

    await adapter.send_buttons(
        user_id,
        f"✅ Added *{name}*.",
        [[Button("➕ Add More", "grocery_search_more"),
          Button("🛒 Checkout", "grocery_checkout")]],
    )


async def handle_grocery_checkout(user_id: str, adapter: MessagingAdapter,
                                  session: SessionService) -> None:
    token, address_id = await _require_token_and_address(user_id, adapter)
    if not token:
        return

    try:
        cart = await instamart_client.get_cart(token)
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))
        return

    items = cart.get("items", []) if isinstance(cart, dict) else []
    if not items:
        await adapter.send_message(user_id, OutboundMessage(
            text="Your cart is empty. Search for items to add — e.g. *milk*, *tomatoes*, *rice*."
        ))
        return

    total = _cart_total(cart)
    if total == 0:
        return

    payment_methods = cart.get("availablePaymentMethods", []) if isinstance(cart, dict) else []
    payment_str = payment_methods[0] if payment_methods else "COD"

    lines = []
    for it in items[:10]:
        qty = it.get("quantity", 1)
        price = it.get("price", 0) or it.get("totalPrice", 0)
        price_paise = price * qty if price > 1000 else price * qty * 100
        lines.append(f"• {it.get('name', 'item')} ×{qty} — ₹{price_paise / 100:.2f}")

    await session.update(user_id, {"state": "PAYMENT_PENDING", "order_type": "grocery",
                                   "total": total, "payment_method": payment_str})
    await adapter.send_buttons(
        user_id,
        f"🛒 *Instamart Cart*\n\n" + "\n".join(lines) +
        f"\n\n*Total: ₹{total / 100:.2f}*\nPayment: {payment_str}\nDelivery: your saved address",
        [
            [Button("✅ Place Order", "confirm_pay"), Button("❌ Cancel", "cancel_order")],
            [Button("🗑 Empty Cart", "grocery_clear")],
        ],
    )


async def _clear_cart(user_id: str, adapter: MessagingAdapter,
                      session: SessionService) -> None:
    token, _ = await _require_token_and_address(user_id, adapter)
    if not token:
        return
    try:
        await instamart_client.clear_cart(token)
        await adapter.send_message(user_id, OutboundMessage(text="🗑 Cart cleared."))
    except SwiggyMCPError as e:
        await adapter.send_message(user_id, OutboundMessage(text=f"⚠️ {e.message}"))


def _price_rupees(price) -> float:
    if not price:
        return 0
    return price / 100 if price > 1000 else price


def _cart_total(cart) -> int:
    if not isinstance(cart, dict):
        return 0
    for key in ("total", "grandTotal", "billTotal", "totalAmount"):
        v = cart.get(key)
        if isinstance(v, (int, float)):
            return int(v) if v > 1000 else int(v * 100)
    total = 0
    for it in cart.get("items", []):
        price = it.get("price", 0) or it.get("totalPrice", 0)
        qty = it.get("quantity", 1)
        total += int(price * qty) if price > 1000 else int(price * qty * 100)
    return total
