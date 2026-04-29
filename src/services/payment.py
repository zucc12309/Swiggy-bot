import hashlib
import hmac
from typing import Any, Dict

import razorpay

from config.settings import settings


class PaymentService:
    def __init__(self) -> None:
        self._client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    def create_payment_link(self, amount: int, description: str, order_id: str,
                            callback_url: str) -> Dict[str, Any]:
        return self._client.payment_link.create({
            "amount": amount,
            "currency": "INR",
            "description": description,
            "reference_id": order_id,
            "callback_url": callback_url,
            "callback_method": "get",
        })

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        expected = hmac.new(
            settings.razorpay_webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def create_order(self, amount: int, receipt: str) -> Dict[str, Any]:
        return self._client.order.create({
            "amount": amount,
            "currency": "INR",
            "receipt": receipt,
        })
