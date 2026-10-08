"""Application settings loaded from environment variables (prefix RA_)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RA_", extra="ignore")

    app_name: str = "research-agent"
    debug: bool = False

    database_url: str | None = None
    db_host: str = "127.0.0.1"
    db_port: int = 25432
    db_user: str | None = None
    db_password: str | None = None
    db_name: str | None = None

    data_dir: Path = Path("data")
    log_level: str = "INFO"

    cors_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    auto_create_tables: bool = True

    fetch_timeout_seconds: int = 20
    fetch_lookback_hours: int = 24
    fetch_max_concurrency: int = 8
    enrich_batch_size: int = 6
    enrich_max_items: int = 100

    api_token: str | None = None
    github_token: str | None = None

    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None

    @property
    def db_url(self) -> str:
        """DSN for SQLAlchemy. Prefer RA_DATABASE_URL; otherwise build it from
        RA_DB_* fields so passwords with `@`/`!` are escaped correctly."""
        if self.db_user and self.db_password and self.db_name:
            return URL.create(
                "postgresql+asyncpg",
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
            ).render_as_string(hide_password=False)
        if not self.database_url:
            raise RuntimeError(
                "Database is not configured. Set RA_DB_USER/RA_DB_PASSWORD/RA_DB_NAME "
                "(recommended) or RA_DATABASE_URL in backend/.env."
            )
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
