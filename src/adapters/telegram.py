from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application

from .base import Button, MessagingAdapter, OutboundMessage


class TelegramAdapter(MessagingAdapter):
    def __init__(self, app: Application) -> None:
        self._app = app

    async def send_message(self, user_id: str, message: OutboundMessage) -> None:
        markup = None
        if message.buttons:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(b.text, callback_data=b.callback_data) for b in row]
                 for row in message.buttons]
            )
        await self._app.bot.send_message(
            chat_id=user_id,
            text=message.text,
            reply_markup=markup,
            parse_mode=message.parse_mode,
        )

    async def send_buttons(self, user_id: str, text: str, buttons: List[List[Button]]) -> None:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(b.text, callback_data=b.callback_data) for b in row]
             for row in buttons]
        )
        await self._app.bot.send_message(chat_id=user_id, text=text, reply_markup=markup)

    async def send_location_request(self, user_id: str, prompt: str) -> None:
        from telegram import KeyboardButton, ReplyKeyboardMarkup
        markup = ReplyKeyboardMarkup(
            [[KeyboardButton(text="📍 Share my location", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await self._app.bot.send_message(chat_id=user_id, text=prompt, reply_markup=markup)

    async def send_payment_link(self, user_id: str, url: str, amount: int, description: str) -> None:
        text = f"💳 *{description}*\nAmount: ₹{amount / 100:.2f}\n\n[Pay now]({url})"
        await self._app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
