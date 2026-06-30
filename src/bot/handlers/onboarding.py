"""Onboarding via Swiggy OAuth 2.1 + PKCE.

Phone-OTP onboarding no longer makes sense — Swiggy MCP already requires
its own phone-OTP via the OAuth consent UI. We just hand the user the
authorize URL; Swiggy's UI does phone + OTP; we receive the code on callback.
"""
import logging
import secrets
from typing import Any, Dict

from src.adapters.base import Button, MessagingAdapter, OutboundMessage
from src.services.session import SessionService
from src.services import swiggy_auth

logger = logging.getLogger(__name__)

MAIN_MENU_BUTTONS = [
    [Button("🍔 Order Food", "order_food"), Button("🛒 Order Groceries", "order_grocery")],
    [Button("🪑 Book a Table", "book_table"), Button("🔄 Auto-Restock", "schedules")],
    [Button("📦 My Orders", "my_orders"), Button("⚙️ Settings", "settings")],
]


async def handle_start(user_id: str, adapter: MessagingAdapter, session: SessionService,
                       user_data: Dict[str, Any]) -> None:
    if user_data.get("swiggy_authenticated"):
        await adapter.send_buttons(user_id, "Welcome back! What would you like to do?",
                                   MAIN_MENU_BUTTONS)
        return

    await adapter.send_message(user_id, OutboundMessage(
        text="👋 Hi! I'm your Swiggy assistant.\n\n"
             "I can help you order food, shop on Instamart, book tables, "
             "and set up auto-restock — all in chat.\n\n"
             "First, I need to connect to your Swiggy account."
    ))
    await start_swiggy_oauth(user_id, adapter, session)


async def start_swiggy_oauth(user_id: str, adapter: MessagingAdapter,
                             session: SessionService) -> None:
    """Generate PKCE + authorize URL, store verifier in session, send link."""
    from config.settings import settings
    from src.db.database import AsyncSessionLocal
    from src.models.user import User
    from sqlalchemy import select

    redirect_uri = settings.swiggy_oauth_redirect_uri
    if not redirect_uri or not settings.public_base_url:
        await adapter.send_message(user_id, OutboundMessage(
            text="⚠️ The bot isn't fully configured yet (missing PUBLIC_BASE_URL). "
                 "Please contact the operator."
        ))
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_id)
            db.add(user)

        if not user.swiggy_oauth_client_id:
            try:
                reg = await swiggy_auth.register_client(redirect_uri)
                user.swiggy_oauth_client_id = reg["client_id"]
            except Exception:
                logger.exception("DCR failed for user %s", user_id)
                await adapter.send_message(user_id, OutboundMessage(
                    text="⚠️ Couldn't register with Swiggy right now. Try /start again in a minute."
                ))
                return

        await db.commit()
        client_id = user.swiggy_oauth_client_id

    verifier, challenge = swiggy_auth.generate_pkce()
    state = f"{user_id}:{secrets.token_urlsafe(16)}"

    await session.update(user_id, {
        "state": "ONBOARDING",
        "oauth_verifier": verifier,
        "oauth_state": state,
    })

    authorize_url = swiggy_auth.build_authorize_url(
        client_id, redirect_uri, challenge, state,
    )

    await adapter.send_message(user_id, OutboundMessage(
        text=f"🔗 Tap to connect Swiggy (you'll enter your phone + OTP):\n\n{authorize_url}\n\n"
             f"I'll let you know once you're connected."
    ))


async def complete_onboarding_after_oauth(user_id: str, adapter: MessagingAdapter,
                                          session: SessionService) -> None:
    """Called from /auth/swiggy/callback once tokens are stored. Picks a
    default Swiggy address and lands the user on the main menu."""
    from src.db.database import AsyncSessionLocal
    from src.models.user import User
    from src.services.swiggy_food import SwiggyFoodClient
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.swiggy_access_token:
            await adapter.send_message(user_id, OutboundMessage(
                text="⚠️ Couldn't complete connection. Type /start to try again."
            ))
            return

        food = SwiggyFoodClient()
        try:
            addresses = await food.get_addresses(user.swiggy_access_token)
        except Exception:
            logger.exception("get_addresses failed during onboarding")
            addresses = []

        if not addresses:
            await session.update(user_id, {"state": "IDLE", "swiggy_authenticated": True})
            await adapter.send_message(user_id, OutboundMessage(
                text="✅ Connected to Swiggy! You don't have any saved addresses yet — "
                     "add one in the Swiggy app, then come back and type /start."
            ))
            return

        if len(addresses) == 1:
            addr = addresses[0]
            user.swiggy_selected_address_id = addr.get("id")
            user.swiggy_selected_address_label = addr.get("label") or addr.get("addressLine", "Default")
            await db.commit()
            await session.update(user_id, {"state": "IDLE", "swiggy_authenticated": True,
                                           "address_id": addr.get("id")})
            await adapter.send_buttons(
                user_id,
                f"✅ Connected! Using your *{user.swiggy_selected_address_label}* address.\n\n"
                f"What would you like to do?",
                MAIN_MENU_BUTTONS,
            )
            return

        await session.update(user_id, {"state": "ONBOARDING", "step": "pick_address",
                                       "addresses": addresses})
        buttons = [[Button(f"📍 {(a.get('label') or a.get('addressLine') or 'Address')[:30]}",
                           f"pick_addr_{i}")]
                   for i, a in enumerate(addresses[:5])]
        await adapter.send_buttons(user_id,
                                   "✅ Connected! Which address would you like to use?",
                                   buttons)


async def handle_address_pick(user_id: str, idx: int, adapter: MessagingAdapter,
                              session: SessionService) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.user import User
    from sqlalchemy import select

    sess = await session.get(user_id)
    addresses = (sess or {}).get("addresses", [])
    if idx >= len(addresses):
        return
    addr = addresses[idx]

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalar_one()
        user.swiggy_selected_address_id = addr.get("id")
        user.swiggy_selected_address_label = addr.get("label") or addr.get("addressLine", "Default")
        await db.commit()

    await session.update(user_id, {"state": "IDLE", "swiggy_authenticated": True,
                                   "address_id": addr.get("id")})
    await adapter.send_buttons(
        user_id,
        f"✅ Using your *{addr.get('label') or 'address'}*. What would you like to do?",
        MAIN_MENU_BUTTONS,
    )
