import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
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
    update = Update.de_json(data, get_conversation_manager()._adapter._app.bot)

    msg = None
    if update.message:
        tg_msg = update.message
        user_id = str(tg_msg.chat_id)
        if tg_msg.location:
            msg = IncomingMessage(user_id=user_id, text=None, lat=tg_msg.location.latitude, lng=tg_msg.location.longitude)
        else:
            msg = IncomingMessage(user_id=user_id, text=tg_msg.text or "")
    elif update.callback_query:
        cb = update.callback_query
        user_id = str(cb.message.chat_id)
        msg = IncomingMessage(user_id=user_id, text=None, callback_data=cb.data)
        await cb.answer()

    if msg:
        background_tasks.add_task(get_conversation_manager().handle, msg)

    return {"ok": True}


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
    # Phase 2: parse WhatsApp payload and dispatch to ConversationManager
    logger.info("WhatsApp webhook received")
    return {"ok": True}


@router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request) -> int:
    params = request.query_params
    if params.get("hub.verify_token") == settings.whatsapp_verify_token:
        return int(params.get("hub.challenge", 0))
    raise HTTPException(status_code=403, detail="Invalid verify token")
