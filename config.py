from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_channel: str = Field(default="@mansurfrench", alias="TELEGRAM_CHANNEL")
    admin_telegram_user_id: int = Field(alias="ADMIN_TELEGRAM_USER_ID")

    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5-mini", alias="OPENAI_MODEL")
    openai_reviewer_model: str = Field(default="gpt-5-mini", alias="OPENAI_REVIEWER_MODEL")

    database_url: str = Field(alias="DATABASE_URL")
    timezone: str = Field(default="Europe/Paris", alias="TIMEZONE")

    morning_hour: int = Field(default=9, alias="MORNING_HOUR")
    morning_minute: int = Field(default=0, alias="MORNING_MINUTE")
    evening_hour: int = Field(default=19, alias="EVENING_HOUR")
    evening_minute: int = Field(default=30, alias="EVENING_MINUTE")

    questions_per_block: int = 3
    content_version: str = "4.0"
    post_delay_seconds: float = Field(default=2.0, alias="POST_DELAY_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    port: int = Field(default=8080, alias="PORT")
    openai_timeout_seconds: float = Field(default=120.0, alias="OPENAI_TIMEOUT_SECONDS")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://") and "+psycopg" not in value:
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("morning_hour", "evening_hour")
    @classmethod
    def valid_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("Hour must be between 0 and 23")
        return value

    @field_validator("morning_minute", "evening_minute")
    @classmethod
    def valid_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError("Minute must be between 0 and 59")
        return value


@lru_cache
def settings() -> Settings:
    return Settings()
