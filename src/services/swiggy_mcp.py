"""Base JSON-RPC MCP client for Swiggy.

Swiggy MCP is streamable HTTP, NOT REST. Every tool call is:
  POST /{server} { jsonrpc, method: "tools/call", params: { name, arguments }, id }

Each user has their own OAuth access token — stored per-user in the database
and passed as Authorization: Bearer header.
"""
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class SwiggyMCPError(Exception):
    """Raised when a Swiggy MCP tool returns success=false or transport fails."""

    def __init__(self, message: str, http_status: Optional[int] = None,
                 jsonrpc_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.jsonrpc_code = jsonrpc_code

    @property
    def is_auth(self) -> bool:
        return self.http_status == 401 or self.jsonrpc_code == -32001

    @property
    def is_retryable(self) -> bool:
        if not self.http_status:
            return False
        return 500 <= self.http_status < 600


class SwiggyMCPClient:
    """JSON-RPC MCP client for one Swiggy server (Food / Instamart / Dineout)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._call_id = 0

    async def call_tool(self, access_token: str, name: str,
                        arguments: Optional[Dict[str, Any]] = None,
                        timeout: float = 5.0) -> Dict[str, Any]:
        """Invoke a tool via JSON-RPC tools/call. Returns the `data` field on success."""
        self._call_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
            "id": self._call_id,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                r = await client.post(
                    self._base_url,
                    headers={"Authorization": f"Bearer {access_token}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
            except httpx.TimeoutException as e:
                raise SwiggyMCPError(f"timeout calling {name}") from e
            except httpx.HTTPError as e:
                raise SwiggyMCPError(f"transport error calling {name}: {e}") from e

            if r.status_code == 401:
                raise SwiggyMCPError("session expired", http_status=401)

            try:
                body = r.json()
            except ValueError:
                raise SwiggyMCPError(f"non-JSON response from {name}: {r.text[:200]}",
                                     http_status=r.status_code)

            if "error" in body:
                err = body["error"]
                raise SwiggyMCPError(
                    err.get("message", "unknown JSON-RPC error"),
                    http_status=r.status_code,
                    jsonrpc_code=err.get("code"),
                )

            result = body.get("result", {})
            if isinstance(result, dict) and result.get("success") is False:
                msg = (result.get("error") or {}).get("message", "tool failed")
                raise SwiggyMCPError(msg, http_status=r.status_code)

            if isinstance(result, dict) and "data" in result:
                return result["data"]
            return result
