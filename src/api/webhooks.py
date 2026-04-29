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


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request, background_tasks: BackgroundTasks,
                           x_razorpay_signature: str = Header(default="")) -> dict:
    body = await request.body()
    from src.services.payment import PaymentService
    svc = PaymentService()
    if not svc.verify_webhook_signature(body, x_razorpay_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()
    event = data.get("event")

    if event == "payment_link.paid":
        background_tasks.add_task(_handle_payment_success, data)
    elif event in {"payment.failed", "payment_link.expired"}:
        background_tasks.add_task(_handle_payment_failure, data)

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
    logger.info("WhatsApp webhook received (Phase 2)")
    return {"ok": True}


@router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request) -> int:
    params = request.query_params
    if params.get("hub.verify_token") == settings.whatsapp_verify_token:
        return int(params.get("hub.challenge", 0))
    raise HTTPException(status_code=403, detail="Invalid verify token")


async def _handle_payment_success(data: dict) -> None:
    from src.db.database import AsyncSessionLocal
    from src.models.order import Order, OrderStatus
    from src.services.swiggy_food import SwiggyFoodClient
    from sqlalchemy import select

    payload = data.get("payload", {})
    reference_id = payload.get("payment_link", {}).get("entity", {}).get("reference_id")
    if not reference_id:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Order).where(Order.razorpay_order_id == reference_id))
        order = result.scalar_one_or_none()
        if not order:
            logger.warning("Order not found for reference_id %s", reference_id)
            return

        order.status = OrderStatus.PLACED
        await db.commit()
        logger.info("Payment confirmed for order %s", order.id)


async def _handle_payment_failure(data: dict) -> None:
    payload = data.get("payload", {})
    reference_id = payload.get("payment_link", {}).get("entity", {}).get("reference_id")
    logger.warning("Payment failed for reference_id %s", reference_id)

    from src.db.database import AsyncSessionLocal
    from src.models.order import Order, OrderStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Order).where(Order.razorpay_order_id == reference_id))
        order = result.scalar_one_or_none()
        if order:
            order.status = OrderStatus.FAILED
            await db.commit()
