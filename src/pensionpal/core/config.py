from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "pensionpal"
    app_env: Literal["local", "ci", "production"]
    log_level: str = "INFO"
    data_file: str = "data/sample_records.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
