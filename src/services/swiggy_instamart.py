from typing import Any, Dict, List, Optional

import httpx

from config.settings import settings


class SwiggyInstamartClient:
    """Swiggy Instamart MCP API client."""

    def __init__(self) -> None:
        self._base_url = settings.swiggy_instamart_mcp_url
        self._headers = {"Authorization": f"Bearer {settings.swiggy_mcp_token}"}

    async def search_products(self, query: str, lat: float, lng: float) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self._base_url}/products/search", headers=self._headers,
                                 params={"q": query, "lat": lat, "lng": lng})
            r.raise_for_status()
            return r.json()["products"]

    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self._base_url}/products/{product_id}", headers=self._headers)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    async def get_products_batch(self, product_ids: List[str]) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{self._base_url}/products/batch", headers=self._headers,
                                  json={"product_ids": product_ids})
            r.raise_for_status()
            return r.json()["products"]

    async def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{self._base_url}/orders", headers=self._headers, json=payload)
            r.raise_for_status()
            return r.json()
