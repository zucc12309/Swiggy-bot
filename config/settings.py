from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    debug: bool = False
    messaging_platform: str = "telegram"  # "telegram" | "whatsapp"
    public_base_url: str = ""  # used for OAuth redirect, e.g. https://bot.example.com

    # Database
    database_url: str = "postgresql+asyncpg://swiggy_bot:changeme@localhost:5432/swiggy_bot"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # WhatsApp (Phase 2)
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_webhook_secret: str = ""

    # Swiggy MCP — OAuth 2.1 + PKCE. Client registered via DCR on first use.
    # No static API token: each user gets their own access token via authorize flow.
    swiggy_food_mcp_url: str = "https://mcp.swiggy.com/food"
    swiggy_instamart_mcp_url: str = "https://mcp.swiggy.com/im"
    swiggy_dineout_mcp_url: str = "https://mcp.swiggy.com/dineout"

    @property
    def swiggy_oauth_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/auth/swiggy/callback"


settings = Settings()
