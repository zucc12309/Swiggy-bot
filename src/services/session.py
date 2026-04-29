import json
from typing import Any, Dict, Optional

import redis.asyncio as aioredis

from config.settings import settings

SESSION_TTL = 1800  # 30 minutes


class SessionService:
    def __init__(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    def _key(self, user_id: str) -> str:
        return f"session:{user_id}"

    async def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        data = await self._redis.get(self._key(user_id))
        return json.loads(data) if data else None

    async def set(self, user_id: str, state: Dict[str, Any]) -> None:
        await self._redis.setex(self._key(user_id), SESSION_TTL, json.dumps(state))

    async def update(self, user_id: str, partial: Dict[str, Any]) -> None:
        current = await self.get(user_id) or {}
        current.update(partial)
        await self.set(user_id, current)

    async def delete(self, user_id: str) -> None:
        await self._redis.delete(self._key(user_id))

    async def get_state(self, user_id: str) -> str:
        session = await self.get(user_id)
        return session.get("state", "IDLE") if session else "IDLE"
