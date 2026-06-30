"""Swiggy Food MCP client — 14 tools.

All calls go to POST mcp.swiggy.com/food via JSON-RPC tools/call.
v1 constraints: COD only, ₹1000 cart cap, cart bound to one restaurant.
"""
from typing import Any, Dict, List, Optional

from .swiggy_mcp import SwiggyMCPClient


FOOD_CART_CAP_PAISE = 100_000  # ₹1000 v1 cap on Builders Club Food orders


class SwiggyFoodClient:
    def __init__(self) -> None:
        self._mcp = SwiggyMCPClient("https://mcp.swiggy.com/food")

    # Discover
    async def get_addresses(self, token: str) -> List[Dict[str, Any]]:
        result = await self._mcp.call_tool(token, "get_addresses")
        return result if isinstance(result, list) else result.get("addresses", [])

    async def search_restaurants(self, token: str, address_id: str, query: str,
                                 offset: int = 0) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "search_restaurants", {
            "addressId": address_id, "query": query, "offset": offset,
        })

    async def get_restaurant_menu(self, token: str, address_id: str, restaurant_id: str,
                                  page: int = 1, page_size: int = 5) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_restaurant_menu", {
            "addressId": address_id, "restaurantId": restaurant_id,
            "page": page, "pageSize": page_size,
        })

    async def search_menu(self, token: str, address_id: str, query: str,
                         restaurant_id: Optional[str] = None,
                         veg_only: bool = False, offset: int = 0) -> Dict[str, Any]:
        args = {"addressId": address_id, "query": query, "offset": offset,
                "vegFilter": 1 if veg_only else 0}
        if restaurant_id:
            args["restaurantIdOfAddedItem"] = restaurant_id
        return await self._mcp.call_tool(token, "search_menu", args)

    # Cart
    async def update_food_cart(self, token: str, address_id: str, restaurant_id: str,
                               cart_items: List[Dict[str, Any]],
                               restaurant_name: Optional[str] = None) -> Dict[str, Any]:
        args = {"addressId": address_id, "restaurantId": restaurant_id, "cartItems": cart_items}
        if restaurant_name:
            args["restaurantName"] = restaurant_name
        return await self._mcp.call_tool(token, "update_food_cart", args)

    async def get_food_cart(self, token: str, address_id: str,
                            restaurant_name: Optional[str] = None) -> Dict[str, Any]:
        args = {"addressId": address_id}
        if restaurant_name:
            args["restaurantName"] = restaurant_name
        return await self._mcp.call_tool(token, "get_food_cart", args)

    async def flush_food_cart(self, token: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "flush_food_cart")

    async def fetch_food_coupons(self, token: str, restaurant_id: str,
                                 address_id: str,
                                 coupon_code: Optional[str] = None) -> Dict[str, Any]:
        args = {"restaurantId": restaurant_id, "addressId": address_id}
        if coupon_code:
            args["couponCode"] = coupon_code
        return await self._mcp.call_tool(token, "fetch_food_coupons", args)

    async def apply_food_coupon(self, token: str, coupon_code: str,
                                address_id: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "apply_food_coupon", {
            "couponCode": coupon_code, "addressId": address_id,
        })

    # Order — NON-IDEMPOTENT: on 5xx, check get_food_orders before retrying
    async def place_food_order(self, token: str, address_id: str,
                               payment_method: Optional[str] = None) -> Dict[str, Any]:
        args = {"addressId": address_id}
        if payment_method:
            args["paymentMethod"] = payment_method
        return await self._mcp.call_tool(token, "place_food_order", args, timeout=10.0)

    # Track
    async def get_food_orders(self, token: str, address_id: str,
                              order_count: int = 5) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_food_orders", {
            "addressId": address_id, "orderCount": order_count,
        })

    async def get_food_order_details(self, token: str, order_id: str) -> Dict[str, Any]:
        return await self._mcp.call_tool(token, "get_food_order_details",
                                         {"orderId": order_id})

    async def track_food_order(self, token: str,
                               order_id: Optional[str] = None) -> Dict[str, Any]:
        args = {"orderId": order_id} if order_id else {}
        return await self._mcp.call_tool(token, "track_food_order", args)

    # Support
    async def report_error(self, token: str, tool: str, error_message: str,
                           flow_description: Optional[str] = None,
                           tool_context: Optional[Dict[str, Any]] = None,
                           user_notes: Optional[str] = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {"tool": tool, "errorMessage": error_message, "domain": "food"}
        if flow_description:
            args["flowDescription"] = flow_description
        if tool_context:
            args["toolContext"] = tool_context
        if user_notes:
            args["userNotes"] = user_notes
        return await self._mcp.call_tool(token, "report_error", args)
