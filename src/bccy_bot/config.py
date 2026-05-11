from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(..., description="Telegram Bot Token from @BotFather")
    database_url: str = Field(..., description="SQLAlchemy async database URL")
    initial_super_admin_id: int = Field(..., description="Initial super admin Telegram user ID")
    log_level: str = Field("INFO", description="Logging level")
    timezone: str = Field("Asia/Shanghai", description="Display timezone for logs/cards")


settings = Settings()  # type: ignore[call-arg]
