from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Resy
    resy_api_key: str = ""
    resy_auth_token: str = ""
    resy_payment_method_id: str = ""
    resy_email: str = ""
    resy_password: str = ""

    # OpenTable
    opentable_email: str = ""
    opentable_password: str = ""

    # Gmail
    gmail_email: str = ""
    gmail_app_password: str = ""
    gmail_poll_interval_seconds: int = 60

    # User info
    user_first_name: str = ""
    user_last_name: str = ""
    user_phone: str = ""
    user_email: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./restaurant_agent.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
