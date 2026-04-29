from typing import List

import httpx

from .base import Button, MessagingAdapter, OutboundMessage


class WhatsAppAdapter(MessagingAdapter):
    """Phase 2 — Meta Cloud API adapter."""

    def __init__(self, phone_number_id: str, access_token: str) -> None:
        self._phone_number_id = phone_number_id
        self._base_url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async def send_message(self, user_id: str, message: OutboundMessage) -> None:
        async with httpx.AsyncClient() as client:
            await client.post(self._base_url, headers=self._headers, json={
                "messaging_product": "whatsapp",
                "to": user_id,
                "type": "text",
                "text": {"body": message.text},
            })

    async def send_buttons(self, user_id: str, text: str, buttons: List[List[Button]]) -> None:
        flat = [b for row in buttons for b in row][:3]  # WhatsApp max 3 reply buttons
        async with httpx.AsyncClient() as client:
            await client.post(self._base_url, headers=self._headers, json={
                "messaging_product": "whatsapp",
                "to": user_id,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {"buttons": [
                        {"type": "reply", "reply": {"id": b.callback_data, "title": b.text[:20]}}
                        for b in flat
                    ]},
                },
            })

    async def send_location_request(self, user_id: str, prompt: str) -> None:
        await self.send_message(user_id, OutboundMessage(text=prompt + "\n\nPlease share your location."))

    async def send_payment_link(self, user_id: str, url: str, amount: int, description: str) -> None:
        text = f"💳 {description}\nAmount: ₹{amount / 100:.2f}\n\nPay here: {url}"
        await self.send_message(user_id, OutboundMessage(text=text))
