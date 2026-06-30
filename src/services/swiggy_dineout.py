"""Swiggy Dineout MCP client — 8 tools.

All calls go to POST mcp.swiggy.com/dineout via JSON-RPC tools/call.
v1 constraints: FREE reservations only (no paid deals).
"""
from typing import Any, Dict, List, Optional

from .swiggy_mcp import SwiggyMCPClient


class SwiggyDineoutClient:
    def __init__(self) -> None:
        self._mcp = SwiggyMCPClient("https://mcp.swiggy.com/dineout")

    # Find
    async def get_saved_locations(self, token: str) -> List[Dict[str, Any]]:
        result = await self._mcp.call_tool(token, "get_saved_locations")
        return result if isinstance(result, list) else result.get("locations", [])

    async def search_restaurants_dineout(self, token: str, query: str,
                                         entity_type: Optional[str] = None,
                                         address_id: Optional[str] = None,
                                         lat: Optional[float] = None,
                                         lng: Optional[float] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {"query": query}
        if entity_type:
            args["entityType"] = entity_type
        if address_id:
            args["addressId"] = address_id
        if lat is not None:
            args["latitude"] = lat
        if lng is not None:
            args["longitude"] = lng
        return await self._mcp.call_tool(token, "search_restaurants_dineout", args)

    async def get_restaurant_details(self, token: str, restaurant_id: str,
                                     lat: float, lng: float) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_restaurant_details", {
            "restaurantId": restaurant_id, "latitude": lat, "longitude": lng,
        })

    # Reserve
    async def get_available_slots(self, token: str, restaurant_id: str,
                                  date: str, lat: float, lng: float) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_available_slots", {
            "restaurantId": restaurant_id, "date": date,
            "latitude": lat, "longitude": lng,
        })

    async def book_table(self, token: str, restaurant_id: str, slot_id: int,
                         item_id: str, reservation_time: int,
                         guest_count: int, lat: float, lng: float) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "book_table", {
            "restaurantId": restaurant_id,
            "slotId": slot_id,
            "itemId": item_id,
            "reservationTime": reservation_time,
            "guestCount": guest_count,
            "latitude": lat,
            "longitude": lng,
        }, timeout=10.0)

    async def create_cart(self, token: str, restaurant_id: str, cart_type: str,
                          lat: float, lng: float, **kwargs) -> Dict[str, Any]:
        args = {
            "restaurantId": restaurant_id,
            "cartType": cart_type,
            "latitude": lat,
            "longitude": lng,
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        return await self._mcp.call_tool(token, "create_cart", args)

    # Manage
    async def get_booking_status(self, token: str, order_id: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_booking_status", {"orderId": order_id})

    # Support
    async def report_error(self, token: str, tool: str, error_message: str,
                           flow_description: Optional[str] = None,
                           tool_context: Optional[Dict[str, Any]] = None,
                           user_notes: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {"tool": tool, "errorMessage": error_message, "domain": "dineout"}
        if flow_description:
            args["flowDescription"] = flow_description
        if tool_context:
            args["toolContext"] = tool_context
        if user_notes:
            args["userNotes"] = user_notes
        return await self._mcp.call_tool(token, "report_error", args)
