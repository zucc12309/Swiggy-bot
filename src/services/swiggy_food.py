from typing import Any, Dict, List

import httpx

from config.settings import settings


class SwiggyFoodClient:
    """Swiggy Food MCP API client."""

    def __init__(self) -> None:
        self._base_url = settings.swiggy_food_mcp_url
        self._headers = {"Authorization": f"Bearer {settings.swiggy_mcp_token}"}

    async def search_restaurants(self, query: str, lat: float, lng: float) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self._base_url}/restaurants/search", headers=self._headers,
                                 params={"q": query, "lat": lat, "lng": lng, "limit": 3})
            r.raise_for_status()
            return r.json()["restaurants"]

    async def get_menu(self, restaurant_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self._base_url}/restaurants/{restaurant_id}/menu", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{self._base_url}/orders", headers=self._headers, json=payload)
            r.raise_for_status()
            return r.json()

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self._base_url}/orders/{order_id}", headers=self._headers)
            r.raise_for_status()
            return r.json()
