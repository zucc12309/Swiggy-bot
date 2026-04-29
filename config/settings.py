from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    debug: bool = False
    messaging_platform: str = "telegram"  # "telegram" | "whatsapp"

    # Database
    database_url: str = "postgresql+asyncpg://swiggy_bot:changeme@localhost:5432/swiggy_bot"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Payments
    payment_callback_base_url: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # WhatsApp (Phase 2)
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_webhook_secret: str = ""

    # Swiggy MCP
    swiggy_mcp_token: str = ""
    swiggy_food_mcp_url: str = "https://mcp.swiggy.com/food/v1"
    swiggy_instamart_mcp_url: str = "https://mcp.swiggy.com/instamart/v1"
    swiggy_dineout_mcp_url: str = "https://mcp.swiggy.com/dineout/v1"

    # Razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""


settings = Settings()
