"""OAuth 2.1 + PKCE flow for Swiggy MCP authentication.

Swiggy MCP requires per-user OAuth — there is no static API key.
Access tokens live 5 days. No refresh tokens in v1.0 — re-run authorize on 401.
"""
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

SWIGGY_OAUTH_BASE = "https://mcp.swiggy.com"
AUTHORIZE_URL = f"{SWIGGY_OAUTH_BASE}/auth/authorize"
TOKEN_URL = f"{SWIGGY_OAUTH_BASE}/auth/token"
LOGOUT_URL = f"{SWIGGY_OAUTH_BASE}/auth/logout"
REGISTER_URL = f"{SWIGGY_OAUTH_BASE}/auth/register"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce() -> Tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


async def register_client(redirect_uri: str) -> dict:
    """Dynamic client registration (RFC 7591). Returns {client_id, ...}."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(REGISTER_URL, json={
            "client_name": "Swiggy Bot",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        })
        r.raise_for_status()
        return r.json()


def build_authorize_url(client_id: str, redirect_uri: str,
                        code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "mcp:tools mcp:resources mcp:prompts",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, code_verifier: str,
                        client_id: str, redirect_uri: str) -> dict:
    """Exchange auth code for access token. Returns full token response."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(TOKEN_URL, json={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        })
        r.raise_for_status()
        return r.json()


async def logout(access_token: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {access_token}"})


def is_token_expired(expires_at: Optional[datetime]) -> bool:
    if not expires_at:
        return True
    return datetime.now(timezone.utc) >= expires_at - timedelta(seconds=60)


def calc_expires_at(expires_in: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)
