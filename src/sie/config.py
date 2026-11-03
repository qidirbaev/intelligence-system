"""Application settings (environment and optional `.env`). Secrets are never printed or logged."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DATABASE_URL = "postgresql+psycopg://sie:sie_dev_only@127.0.0.1:5432/sie"


class Settings(BaseSettings):
    """All runtime configuration. Environment variables use the `SIE_` prefix.

    `DATABASE_URL`, `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are also read without the prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="SIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = Field(
        default=DEV_DATABASE_URL,
        validation_alias=AliasChoices("DATABASE_URL", "SIE_DATABASE_URL"),
    )
    tenant_id: str = "default"  # single fixed value in the MVP (TZ section 4)

    log_level: str = "INFO"
    log_json: bool = True

    # CG-6: where data is stored by default, and which model providers may receive text.
    data_region: str = "UZ"
    providers_file: Path | None = None

    # Secrets (CG-5): optional here, required in prod where they are used.
    hmac_secret: SecretStr | None = None  # commenter author_hash (TZ 7.5)
    session_encryption_key: SecretStr | None = None  # encrypts Telegram session files
    telegram_api_id: int | None = Field(
        default=None, validation_alias=AliasChoices("TELEGRAM_API_ID", "SIE_TELEGRAM_API_ID")
    )
    telegram_api_hash: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("TELEGRAM_API_HASH", "SIE_TELEGRAM_API_HASH")
    )

    @field_validator("database_url")
    @classmethod
    def _supported_database(cls, value: str) -> str:
        if not value.startswith(("postgresql", "sqlite")):
            raise ValueError("database_url must start with 'postgresql' or 'sqlite'")
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown log level: {value}")
        return level

    @model_validator(mode="after")
    def _prod_requires_secrets(self) -> "Settings":
        if self.env == "prod":
            missing = [
                name
                for name in ("hmac_secret", "session_encryption_key")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"env=prod requires: {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, loaded once. Call `clear_settings_cache()` in tests."""
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
