from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Button:
    text: str
    callback_data: str


@dataclass
class OutboundMessage:
    text: str
    buttons: Optional[List[List[Button]]] = None
    parse_mode: Optional[str] = None


class MessagingAdapter(ABC):
    """Platform-agnostic messaging interface. Swap Telegram ↔ WhatsApp via config."""

    @abstractmethod
    async def send_message(self, user_id: str, message: OutboundMessage) -> None: ...

    @abstractmethod
    async def send_buttons(self, user_id: str, text: str, buttons: List[List[Button]]) -> None: ...

    @abstractmethod
    async def send_location_request(self, user_id: str, prompt: str) -> None: ...

    @abstractmethod
    async def send_payment_link(self, user_id: str, url: str, amount: int, description: str) -> None: ...
