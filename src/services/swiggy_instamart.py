"""Swiggy Instamart MCP client — 13 tools.

All calls go to POST mcp.swiggy.com/im via JSON-RPC tools/call.
v1 constraints: COD only, cart bound to delivery address (clear_cart before address switch).
"""
from typing import Any, Dict, List, Optional

from .swiggy_mcp import SwiggyMCPClient


class SwiggyInstamartClient:
    def __init__(self) -> None:
        self._mcp = SwiggyMCPClient("https://mcp.swiggy.com/im")

    # Discover
    async def get_addresses(self, token: str) -> List[Dict[str, Any]]:
        result = await self._mcp.call_tool(token, "get_addresses")
        return result if isinstance(result, list) else result.get("addresses", [])

    async def create_address(self, token: str, full_address: str, address_line: str,
                             address_line2: str, city: str, postal_code: str,
                             latitude: float, longitude: float,
                             user_name: str, user_phone: str,
                             address_category: str = "HOME",
                             locality: Optional[str] = None,
                             address_tag: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {
            "fullAddress": full_address,
            "addressLine": address_line,
            "addressLine2": address_line2,
            "city": city,
            "postalCode": postal_code,
            "latitude": latitude,
            "longitude": longitude,
            "addressCategory": address_category,
            "userName": user_name,
            "userPhone": user_phone,
        }
        if locality:
            args["locality"] = locality
        if address_tag:
            args["addressTag"] = address_tag
        return await self._mcp.call_tool(token, "create_address", args)

    async def delete_address(self, token: str, address_id: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "delete_address", {"addressId": address_id})

    async def search_products(self, token: str, address_id: str, query: str,
                              offset: int = 0) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "search_products", {
            "addressId": address_id, "query": query, "offset": offset,
        })

    async def your_go_to_items(self, token: str, address_id: str,
                               offset: int = 0) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "your_go_to_items", {
            "addressId": address_id, "offset": offset,
        })

    # Cart
    async def update_cart(self, token: str, address_id: str,
                          items: List[Dict[str, Any]]) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "update_cart", {
            "selectedAddressId": address_id, "items": items,
        })

    async def get_cart(self, token: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_cart")

    async def clear_cart(self, token: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "clear_cart")

    # Order — NON-IDEMPOTENT: on 5xx, check get_orders before retrying
    async def checkout(self, token: str, address_id: str,
                       payment_method: Optional[str] = None) -> Dict[str, Any]:
        args = {"addressId": address_id}
        if payment_method:
            args["paymentMethod"] = payment_method
        return await self._mcp.call_tool(token, "checkout", args, timeout=10.0)

    # Track
    async def get_orders(self, token: str, count: int = 10,
                         order_type: str = "DASH",
                         active_only: bool = False) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_orders", {
            "count": count, "orderType": order_type, "activeOnly": active_only,
        })

    async def get_order_details(self, token: str, order_id: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_order_details", {"orderId": order_id})

    async def track_order(self, token: str, order_id: str,
                          lat: float, lng: float) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "track_order", {
            "orderId": order_id, "lat": lat, "lng": lng,
        })

    # Support
    async def report_error(self, token: str, tool: str, error_message: str,
                           flow_description: Optional[str] = None,
                           tool_context: Optional[Dict[str, Any]] = None,
                           user_notes: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {"tool": tool, "errorMessage": error_message, "domain": "im"}
        if flow_description:
            args["flowDescription"] = flow_description
        if tool_context:
            args["toolContext"] = tool_context
        if user_notes:
            args["userNotes"] = user_notes
        return await self._mcp.call_tool(token, "report_error", args)
