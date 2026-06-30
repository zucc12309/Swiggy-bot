import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from telegram import Update
from telegram.ext import Application

from config.settings import settings
from src.bot.conversation import ConversationManager, IncomingMessage
from src.services.session import SessionService

router = APIRouter()
logger = logging.getLogger(__name__)

_telegram_app: Application | None = None
_conversation_manager: ConversationManager | None = None


def get_conversation_manager() -> ConversationManager:
    global _telegram_app, _conversation_manager
    if _conversation_manager is None:
        from src.adapters.telegram import TelegramAdapter
        _telegram_app = Application.builder().token(settings.telegram_bot_token).build()
        adapter = TelegramAdapter(_telegram_app)
        session = SessionService()
        _conversation_manager = ConversationManager(adapter, session)
    return _conversation_manager


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    data = await request.json()
    mgr = get_conversation_manager()
    update = Update.de_json(data, mgr._adapter._app.bot)

    msg = None
    if update.message:
        tg_msg = update.message
        user_id = str(tg_msg.chat_id)
        if tg_msg.location:
            msg = IncomingMessage(user_id=user_id, text=None,
                                  lat=tg_msg.location.latitude, lng=tg_msg.location.longitude)
        else:
            msg = IncomingMessage(user_id=user_id, text=tg_msg.text or "")
    elif update.callback_query:
        cb = update.callback_query
        user_id = str(cb.message.chat_id)
        msg = IncomingMessage(user_id=user_id, text=None, callback_data=cb.data)
        await cb.answer()

    if msg:
        background_tasks.add_task(mgr.handle, msg)

    return {"ok": True}


@router.get("/auth/swiggy/callback", response_class=HTMLResponse)
async def swiggy_oauth_callback(request: Request, code: str = "", state: str = "",
                                error: str = "") -> str:
    """Receive Swiggy OAuth code, exchange for access token, store on user."""
    from src.db.database import AsyncSessionLocal
    from src.models.user import User
    from src.services import swiggy_auth
    from sqlalchemy import select

    if error:
        return f"<h1>Connection failed</h1><p>{error}</p><p>Return to the bot and type /start.</p>"

    if not code or not state or ":" not in state:
        raise HTTPException(status_code=400, detail="missing code or state")

    telegram_id = state.split(":", 1)[0]
    session = SessionService()
    sess = await session.get(telegram_id)
    if not sess or sess.get("oauth_state") != state:
        raise HTTPException(status_code=400, detail="state mismatch — possible CSRF")

    verifier = sess.get("oauth_verifier")
    if not verifier:
        raise HTTPException(status_code=400, detail="no PKCE verifier in session")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user or not user.swiggy_oauth_client_id:
            raise HTTPException(status_code=400, detail="user not found")

        try:
            token_resp = await swiggy_auth.exchange_code(
                code, verifier, user.swiggy_oauth_client_id,
                settings.swiggy_oauth_redirect_uri,
            )
        except Exception:
            logger.exception("token exchange failed for user %s", telegram_id)
            return "<h1>Connection failed</h1><p>Couldn't exchange the code for a token. Please try /start again.</p>"

        user.swiggy_access_token = token_resp["access_token"]
        user.swiggy_token_expires_at = swiggy_auth.calc_expires_at(token_resp.get("expires_in", 432000))
        await db.commit()

    # Clear the verifier from session and notify the bot
    await session.update(telegram_id, {"oauth_verifier": None, "oauth_state": None})

    from src.bot.handlers import onboarding
    mgr = get_conversation_manager()
    try:
        await onboarding.complete_onboarding_after_oauth(telegram_id, mgr._adapter, session)
    except Exception:
        logger.exception("completing onboarding failed")

    return ("<h1>✅ Connected!</h1>"
            "<p>You can close this tab and return to Telegram.</p>")


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks,
                           x_hub_signature_256: str = Header(default="")) -> dict:
    body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.whatsapp_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()
    logger.info("WhatsApp webhook received (Phase 2)")
    return {"ok": True}


@router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request) -> int:
    params = request.query_params
    if params.get("hub.verify_token") == settings.whatsapp_verify_token:
        return int(params.get("hub.challenge", 0))
    raise HTTPException(status_code=403, detail="Invalid verify token")
