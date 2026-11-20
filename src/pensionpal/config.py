from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pensionpal.db.url import to_asyncpg_url


class Settings(BaseSettings):
    app_name: str = "pensionpal"
    app_env: Literal["local", "ci", "production"]
    log_level: str = "INFO"
    data_file: Path = Path("data/sample_records.json")
    database_url: str = "postgresql://localhost:5432/pensionpal"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _fix_db_url(cls, v: str) -> str:
        return to_asyncpg_url(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# keep backward-compatible import
settings = get_settings()
